"""
Tests for V2 Feature 4: Conflict and Staleness Flags.

Verifies:
  1. Job change detection between successive organizations.
  2. Concurrent source disagreement on primary affiliations.
  3. Disparate occupation/sector conflicts flagged with high severity.
  4. Staleness detection (claims older than 90 days or marked is_stale).
  5. Architecture guardrail: Claims are NEVER deleted or overwritten by flags.
  6. Integration with Search and Persons API endpoints.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.model_adapter import ModelAdapter
from app.core.collector import CollectedSource
from app.core.conflict_detector import (
    _detect_occupation_conflicts,
    _detect_organization_conflicts,
    _detect_staleness,
    detect_conflicts_and_staleness,
)
from app.core.discovery import CandidateURL
from app.core.orchestrator import run_search
from app.database import get_db
from app.main import app
from app.models.claim import Claim, ClaimType
from app.models.person import Person, PersonClaim
from app.models.source import Source
from app.schemas.search import ClaimOut, EvidenceItem, SearchHints, SearchRequest


def test_job_change_detection():
    """Transition language ('previously at', 'former') triggers job_change conflict."""
    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()
    now = datetime.now(timezone.utc)

    claims = [
        ClaimOut(
            claim_id=cid1,
            type="organization",
            value="Safaricom PLC",
            confidence=0.9,
            evidence=[
                EvidenceItem(
                    source_url="https://linkedin.com/in/john",
                    source_type="linkedin_profile",
                    excerpt="Previously at Safaricom PLC from 2018 to 2022",
                    retrieved_at=now,
                )
            ],
        ),
        ClaimOut(
            claim_id=cid2,
            type="organization",
            value="Equity Bank Group",
            confidence=0.9,
            evidence=[
                EvidenceItem(
                    source_url="https://equitygroupholdings.com/team/john",
                    source_type="company_page",
                    excerpt="John currently leads engineering at Equity Bank Group",
                    retrieved_at=now,
                )
            ],
        ),
    ]

    conflicts = _detect_organization_conflicts(claims)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "job_change"
    assert conflicts[0].severity == "low"
    assert "career transition" in conflicts[0].description.lower()
    assert cid1 in conflicts[0].claim_ids
    assert cid2 in conflicts[0].claim_ids


def test_source_disagreement_detection():
    """Conflicting active organizations without transition markers trigger source_disagreement."""
    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()
    now = datetime.now(timezone.utc)

    claims = [
        ClaimOut(
            claim_id=cid1,
            type="organization",
            value="KPMG Kenya",
            confidence=0.85,
            evidence=[
                EvidenceItem(
                    source_url="https://kpmg.com/ke/team/alice",
                    source_type="company_page",
                    excerpt="Alice is Senior Tax Manager at KPMG Kenya",
                    retrieved_at=now,
                )
            ],
        ),
        ClaimOut(
            claim_id=cid2,
            type="organization",
            value="PwC Kenya",
            confidence=0.85,
            evidence=[
                EvidenceItem(
                    source_url="https://pwc.com/ke/team/alice",
                    source_type="company_page",
                    excerpt="Alice is Director of Tax Services at PwC Kenya",
                    retrieved_at=now,
                )
            ],
        ),
    ]

    conflicts = _detect_organization_conflicts(claims)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "source_disagreement"
    assert conflicts[0].severity == "medium"
    assert "different primary organizations" in conflicts[0].description


def test_occupation_conflict_detection():
    """Disparate professions (healthcare vs tech) trigger possible_different_person flag."""
    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()
    now = datetime.now(timezone.utc)

    claims = [
        ClaimOut(
            claim_id=cid1,
            type="occupation",
            value="Pediatric Surgeon",
            confidence=0.9,
            evidence=[
                EvidenceItem(
                    source_url="https://hospital.org/staff/peter",
                    source_type="web_page",
                    excerpt="Peter is a Pediatric Surgeon at City Hospital",
                    retrieved_at=now,
                )
            ],
        ),
        ClaimOut(
            claim_id=cid2,
            type="occupation",
            value="Cloud Infrastructure Architect",
            confidence=0.9,
            evidence=[
                EvidenceItem(
                    source_url="https://github.com/peter",
                    source_type="github_profile",
                    excerpt="Cloud Infrastructure Architect and distributed systems engineer",
                    retrieved_at=now,
                )
            ],
        ),
    ]

    conflicts = _detect_occupation_conflicts(claims)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "possible_different_person"
    assert conflicts[0].severity == "high"
    assert "Disparate profession sectors" in conflicts[0].description


def test_staleness_detection_by_age():
    """Claims older than 90 days are flagged as is_stale with staleness_reason."""
    cid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=120)

    claims = [
        ClaimOut(
            claim_id=cid,
            type="occupation",
            value="Software Engineer",
            confidence=0.80,
            evidence=[
                EvidenceItem(
                    source_url="https://oldpage.org/team/mary",
                    source_type="company_page",
                    excerpt="Mary is Software Engineer",
                    retrieved_at=old_date,
                )
            ],
        ),
    ]

    updated, flags = _detect_staleness(claims, now=now)
    assert len(flags) == 1
    assert flags[0].claim_id == cid
    assert flags[0].days_old == 120
    assert updated[0].is_stale is True
    assert updated[0].staleness_reason is not None
    # Confidence slightly calibrated down
    assert updated[0].confidence < 0.80


def test_staleness_detection_by_db_flag():
    """A claim explicitly marked is_stale=True is captured in staleness flags."""
    cid = uuid.uuid4()
    now = datetime.now(timezone.utc)

    claims = [
        ClaimOut(
            claim_id=cid,
            type="occupation",
            value="Lead Counsel",
            confidence=0.75,
            is_stale=True,
            evidence=[
                EvidenceItem(
                    source_url="https://unreachable.org/lawyer",
                    source_type="web_page",
                    excerpt="Lead Counsel",
                    retrieved_at=now,
                )
            ],
        ),
    ]

    updated, flags = _detect_staleness(claims, now=now)
    assert len(flags) == 1
    assert flags[0].claim_id == cid
    assert updated[0].is_stale is True


def test_never_overwrites_or_drops_claims():
    """
    Architecture rule:
    Flags prompt review or lower confidence; they NEVER overwrite or drop a claim.
    """
    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=150)

    claims = [
        ClaimOut(
            claim_id=cid1,
            type="organization",
            value="Company Alpha",
            confidence=0.9,
            evidence=[
                EvidenceItem(source_url="https://alpha.com", source_type="web_page", excerpt="Alpha", retrieved_at=old_date)
            ],
        ),
        ClaimOut(
            claim_id=cid2,
            type="organization",
            value="Company Beta",
            confidence=0.9,
            evidence=[
                EvidenceItem(source_url="https://beta.com", source_type="web_page", excerpt="Beta", retrieved_at=now)
            ],
        ),
    ]

    calibrated_claims, conflicts, staleness = detect_conflicts_and_staleness(claims, now=now)

    # Claim count is strictly preserved!
    assert len(calibrated_claims) == 2
    # Both claim IDs still exist
    assert {c.claim_id for c in calibrated_claims} == {cid1, cid2}
    # Flags are populated
    assert len(conflicts) >= 1
    assert len(staleness) >= 1


@pytest.mark.asyncio
async def test_end_to_end_search_surfaces_conflict_flags(db_session: AsyncSession):
    """End-to-end search returns conflict flags when candidate claims disagree."""
    name = f"David Conflict {uuid.uuid4().hex[:6]}"
    url_a = f"https://company-a.com/team/{uuid.uuid4()}"
    url_b = f"https://company-b.com/team/{uuid.uuid4()}"

    request = SearchRequest(name=name, hints=SearchHints())
    fake_candidates = [
        CandidateURL(url=url_a, source_type="company_page", rank=1),
        CandidateURL(url=url_b, source_type="company_page", rank=2),
    ]
    fake_sources = [
        CollectedSource(url=url_a, domain="company-a.com", title="A", source_type="company_page", text=f"{name} previously worked at Company A."),
        CollectedSource(url=url_b, domain="company-b.com", title="B", source_type="company_page", text=f"{name} currently works at Company B."),
    ]

    async def mock_extract(*args, **kwargs):
        source_url = kwargs.get("source_url") or (args[0] if args else "")
        if source_url == url_a:
            return [
                {"claim_type": "organization", "value": "Company Alpha", "evidence_span": f"{name} previously worked at Company A."},
                {"claim_type": "occupation", "value": "Lead Architect", "evidence_span": "Lead Architect"},
            ]
        return [
            {"claim_type": "organization", "value": "Company Beta", "evidence_span": f"{name} currently works at Company B."},
            {"claim_type": "occupation", "value": "Lead Architect", "evidence_span": "Lead Architect"},
            {"claim_type": "profile_url", "value": url_a, "evidence_span": url_a},  # Cross-link so they merge
        ]

    adapter = AsyncMock(spec=ModelAdapter)

    with (
        patch("app.core.orchestrator.discover_candidates", new_callable=AsyncMock) as mock_disc,
        patch("app.core.orchestrator.collect_sources", new_callable=AsyncMock) as mock_coll,
        patch("app.core.orchestrator.extract_claims", side_effect=mock_extract),
    ):
        mock_disc.return_value = fake_candidates
        mock_coll.return_value = fake_sources

        response = await run_search(request=request, db=db_session, adapter=adapter)

    assert len(response.results) >= 1
    person_res = response.results[0]
    assert len(person_res.conflict_flags) >= 1
    # Check that the job change conflict flag was populated
    assert any(cf.conflict_type in ("job_change", "source_disagreement") for cf in person_res.conflict_flags)


@pytest.mark.asyncio
async def test_persons_api_surfaces_staleness_flags(db_session: AsyncSession):
    """GET /api/v1/persons/{id} returns staleness flags and is_stale indicators."""
    name = f"Old Record {uuid.uuid4().hex[:6]}"
    person = Person(canonical_name=name)
    db_session.add(person)
    await db_session.flush()

    source = Source(
        url=f"https://historical.org/records/{uuid.uuid4()}",
        domain="historical.org",
        title="Historical Staff",
        source_type="web_page",
        retrieved_at=datetime.now(timezone.utc) - timedelta(days=140),
        is_stale=True,
    )
    db_session.add(source)
    await db_session.flush()

    claim = Claim(
        source_id=source.id,
        claim_type=ClaimType.occupation,
        value="Chief Engineer",
        evidence_span="Chief Engineer",
        confidence=0.8,
        is_stale=True,
    )
    db_session.add(claim)
    await db_session.flush()

    pc = PersonClaim(person_id=person.id, claim_id=claim.id, link_confidence=0.85)
    db_session.add(pc)
    await db_session.commit()

    # Override get_db so the ASGI transport uses the same test session,
    # preventing "Future attached to a different loop" errors when run
    # after tests that touch the production connection pool.
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/persons/{person.id}")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["claims"]) == 1
            assert data["claims"][0]["is_stale"] is True
            assert len(data["staleness_flags"]) >= 1
            assert data["staleness_flags"][0]["claim_id"] == str(claim.id)
    finally:
        app.dependency_overrides.pop(get_db, None)
