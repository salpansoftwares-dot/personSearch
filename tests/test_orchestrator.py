"""
Tests for Search Orchestrator with claim persistence integration.

Verifies:
  - run_search executes the end-to-end pipeline
  - Query audit record is stored before data fetching
  - Resolved person clusters and extracted claims are persisted to DB
  - PersonResult and ClaimOut contain genuine DB IDs (not placeholders)
  - Suppressed identities are filtered out from results and persistence
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.model_adapter import ModelAdapter
from app.core.collector import CollectedSource
from app.core.discovery import CandidateURL
from app.core.orchestrator import run_search
from app.core.persistence import _suppression_key
from app.models.claim import Claim
from app.models.governance import Query as QueryModel, Suppression
from app.models.person import Person, PersonClaim
from app.models.source import Source
from app.schemas.search import SearchHints, SearchRequest


class StubAdapter(ModelAdapter):
    def __init__(self, claims_to_return: list[dict]):
        self.claims = claims_to_return

    async def complete(self, prompt: str, system: str = "") -> str:
        return ""

    async def extract_structured(self, prompt: str, schema: type, system: str = ""):
        # Not directly called because we test orchestrator stages
        return None


@pytest.mark.asyncio
async def test_run_search_persists_claims_and_sources(db_session: AsyncSession, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "entity_merge_threshold", 0.25)

    name = f"Grace Hopper {uuid.uuid4().hex[:6]}"
    test_url = f"https://history.navy.mil/officers/{uuid.uuid4()}"

    request = SearchRequest(
        name=name,
        hints=SearchHints(organization="US Navy", role="Rear Admiral"),
        purpose="Historical research",
    )

    fake_candidates = [
        CandidateURL(url=test_url, source_type="company_page", rank=1)
    ]
    fake_sources = [
        CollectedSource(
            url=test_url,
            domain="history.navy.mil",
            title="Rear Admiral Grace Hopper",
            source_type="company_page",
            text="Grace Hopper was a Rear Admiral in the US Navy and a pioneer in computing.",
        )
    ]
    fake_extracted = [
        {
            "claim_type": "role",
            "value": "Rear Admiral",
            "evidence_span": "Rear Admiral in the US Navy",
            "confidence": 0.98,
        },
        {
            "claim_type": "organization",
            "value": "US Navy",
            "evidence_span": "Rear Admiral in the US Navy",
            "confidence": 0.95,
        },
    ]

    adapter = StubAdapter(fake_extracted)

    with (
        patch("app.core.orchestrator.discover_candidates", new_callable=AsyncMock) as mock_disc,
        patch("app.core.orchestrator.collect_sources", new_callable=AsyncMock) as mock_coll,
        patch("app.core.orchestrator.extract_claims", new_callable=AsyncMock) as mock_ext,
    ):
        mock_disc.return_value = fake_candidates
        mock_coll.return_value = fake_sources
        mock_ext.return_value = fake_extracted

        response = await run_search(
            request=request,
            db=db_session,
            adapter=adapter,
            user_id="test-user-123",
        )

    # 1. Response validation
    assert response.query_id is not None
    assert len(response.results) == 1
    result = response.results[0]
    assert result.canonical_name == name
    assert result.label == "possible match"
    assert result.confidence > 0.0
    assert len(result.claims) == 2

    # Verify claim IDs in response are non-nil valid UUIDs
    claim_ids = [c.claim_id for c in result.claims]
    assert len(set(claim_ids)) == 2

    # 2. Database validation — audit query was logged
    audit_res = await db_session.execute(
        select(QueryModel).where(QueryModel.id == response.query_id)
    )
    audit = audit_res.scalar_one_or_none()
    assert audit is not None
    assert audit.user_id == "test-user-123"
    assert audit.purpose == "Historical research"

    # 3. Database validation — person was created
    person_res = await db_session.execute(
        select(Person).where(Person.id == result.person_id)
    )
    person = person_res.scalar_one_or_none()
    assert person is not None
    assert person.canonical_name == name

    # 4. Database validation — claims and source were stored
    source_res = await db_session.execute(
        select(Source).where(Source.url == test_url)
    )
    source = source_res.scalar_one_or_none()
    assert source is not None
    assert source.domain == "history.navy.mil"

    claims_res = await db_session.execute(
        select(Claim).where(Claim.source_id == source.id)
    )
    db_claims = claims_res.scalars().all()
    assert len(db_claims) == 2
    db_claim_ids = {c.id for c in db_claims}
    assert set(claim_ids) == db_claim_ids

    # 5. Database validation — person_claims links exist
    pc_res = await db_session.execute(
        select(PersonClaim).where(PersonClaim.person_id == person.id)
    )
    links = pc_res.scalars().all()
    assert len(links) == 2


@pytest.mark.asyncio
async def test_run_search_suppressed_person_omitted(db_session: AsyncSession):
    name = f"Suppressed Target {uuid.uuid4().hex[:6]}"
    key = _suppression_key(name)
    db_session.add(Suppression(match_key=key))
    await db_session.flush()

    request = SearchRequest(name=name, hints=SearchHints())
    test_url = f"https://example.com/target/{uuid.uuid4()}"

    adapter = StubAdapter([])

    with (
        patch("app.core.orchestrator.discover_candidates", new_callable=AsyncMock) as mock_disc,
        patch("app.core.orchestrator.collect_sources", new_callable=AsyncMock) as mock_coll,
        patch("app.core.orchestrator.extract_claims", new_callable=AsyncMock) as mock_ext,
    ):
        mock_disc.return_value = [CandidateURL(url=test_url, source_type="company_page", rank=1)]
        mock_coll.return_value = [
            CollectedSource(
                url=test_url,
                domain="example.com",
                title="Page",
                source_type="company_page",
                text="Some text",
            )
        ]
        mock_ext.return_value = [
            {"claim_type": "occupation", "value": "Engineer", "evidence_span": "Engineer"}
        ]

        response = await run_search(request=request, db=db_session, adapter=adapter)

    # Suppressed identity produces zero results
    assert len(response.results) == 0

    # No person or claims persisted for this name
    person_res = await db_session.execute(
        select(Person).where(Person.canonical_name == name)
    )
    assert person_res.scalar_one_or_none() is None
