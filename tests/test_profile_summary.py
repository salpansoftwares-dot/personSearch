"""
Tests for V2 Feature 3: Cited Profile Summaries.

Verifies:
  1. Each sentence in a summary cites verified claim IDs.
  2. Untraceable sentences (sentences citing non-existent or hallucinated claims)
     are strictly dropped.
  3. Deterministic synthesis generates valid cited summaries directly from claims.
  4. Search and Person API endpoints return cited summaries.
"""

import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.model_adapter import ModelAdapter
from app.core.summarizer import (
    CitedSentence,
    ProfileSummary,
    generate_profile_summary,
    synthesize_cited_summary,
    validate_and_filter_sentences,
)
from app.database import get_db
from app.main import app
from app.schemas.search import ClaimOut, EvidenceItem, SearchHints, SearchRequest
from app.core.collector import CollectedSource
from app.core.discovery import CandidateURL
from app.core.orchestrator import run_search
from app.models.person import Person


def test_validate_and_filter_sentences_valid():
    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()
    valid_ids = {cid1, cid2}

    raw = [
        {"text": "Alice is a Software Engineer at Acme.", "claim_ids": [str(cid1), str(cid2)]},
    ]

    result = validate_and_filter_sentences(raw, valid_ids)
    assert len(result) == 1
    assert result[0].text == "Alice is a Software Engineer at Acme."
    assert result[0].claim_ids == [cid1, cid2]


def test_validate_and_filter_sentences_untraceable_dropped():
    """
    Architecture rule:
    Each sentence must cite a claim ID; untraceable sentences are removed.
    """
    cid1 = uuid.uuid4()
    valid_ids = {cid1}
    fake_cid = uuid.uuid4()

    raw = [
        {"text": "Alice studied Computer Science at MIT.", "claim_ids": [str(cid1)]},
        {"text": "Alice likes playing chess on weekends.", "claim_ids": []},  # No citations
        {"text": "Alice has 10 patents.", "claim_ids": [str(fake_cid)]},     # Fake citation
        {"text": "Alice is also a marathon runner.", "claim_ids": ["invalid-uuid"]},
    ]

    result = validate_and_filter_sentences(raw, valid_ids)
    assert len(result) == 1
    assert result[0].text == "Alice studied Computer Science at MIT."
    assert result[0].claim_ids == [cid1]


def test_validate_and_filter_sentences_filters_out_invalid_citation_ids():
    """If a sentence cites real + fake IDs, the fake IDs are pruned."""
    cid1 = uuid.uuid4()
    fake_cid = uuid.uuid4()
    valid_ids = {cid1}

    raw = [
        {"text": "Alice works at Acme.", "claim_ids": [str(cid1), str(fake_cid), "not-a-uuid"]},
    ]

    result = validate_and_filter_sentences(raw, valid_ids)
    assert len(result) == 1
    assert result[0].claim_ids == [cid1]


def test_synthesize_cited_summary():
    cid_occ = uuid.uuid4()
    cid_org = uuid.uuid4()
    cid_edu = uuid.uuid4()
    cid_pub = uuid.uuid4()

    claims = [
        {"claim_id": cid_occ, "claim_type": "occupation", "value": "Research Scientist"},
        {"claim_id": cid_org, "claim_type": "organization", "value": "Kenya Medical Research Institute"},
        {"claim_id": cid_edu, "claim_type": "education", "value": "PhD Epidemiology"},
        {"claim_id": cid_pub, "claim_type": "publication", "value": "Malaria Vaccine Efficacy Study"},
    ]

    summary = synthesize_cited_summary("Dr. Grace Muthoni", claims)
    assert summary.full_text
    assert len(summary.sentences) >= 3

    # Check first sentence (role + org)
    s1 = summary.sentences[0]
    assert "Dr. Grace Muthoni is a Research Scientist at Kenya Medical Research Institute." in s1.text
    assert cid_occ in s1.claim_ids
    assert cid_org in s1.claim_ids

    # Check education sentence
    s2 = summary.sentences[1]
    assert "PhD Epidemiology" in s2.text
    assert cid_edu in s2.claim_ids

    # Check publication sentence
    s3 = summary.sentences[2]
    assert "Malaria Vaccine Efficacy Study" in s3.text
    assert cid_pub in s3.claim_ids


@pytest.mark.asyncio
async def test_generate_profile_summary_empty_claims():
    summary = await generate_profile_summary("Unknown Person", [])
    assert summary.full_text == ""
    assert summary.sentences == []


@pytest.mark.asyncio
async def test_generate_profile_summary_with_mock_ai():
    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()

    claims = [
        {"claim_id": cid1, "claim_type": "occupation", "value": "Principal Engineer"},
        {"claim_id": cid2, "claim_type": "organization", "value": "Safaricom"},
    ]

    mock_adapter = AsyncMock(spec=ModelAdapter)
    mock_adapter.complete.return_value = {
        "sentences": [
            {
                "text": "Bob is a Principal Engineer leading cloud architecture at Safaricom.",
                "claim_ids": [str(cid1), str(cid2)],
            }
        ]
    }

    summary = await generate_profile_summary("Bob", claims, adapter=mock_adapter)
    assert len(summary.sentences) == 1
    assert summary.sentences[0].claim_ids == [cid1, cid2]
    assert "Principal Engineer" in summary.sentences[0].text


@pytest.mark.asyncio
async def test_generate_profile_summary_ai_untraceable_falls_back():
    """If AI hallucinates ungrounded sentences, fallback ensures valid citations."""
    cid1 = uuid.uuid4()

    claims = [
        {"claim_id": cid1, "claim_type": "occupation", "value": "Security Lead"},
    ]

    mock_adapter = AsyncMock(spec=ModelAdapter)
    # AI returns sentences with fake / missing claim IDs
    mock_adapter.complete.return_value = {
        "sentences": [
            {
                "text": "Bob was born in Nairobi and loves sailing.",
                "claim_ids": [str(uuid.uuid4())],  # fake claim id
            }
        ]
    }

    summary = await generate_profile_summary("Bob", claims, adapter=mock_adapter)
    # Untraceable sentence was dropped, and synthesizer fallback provided a grounded sentence
    assert len(summary.sentences) == 1
    assert summary.sentences[0].claim_ids == [cid1]
    assert "Bob is a Security Lead." in summary.sentences[0].text


@pytest.mark.asyncio
async def test_end_to_end_search_produces_cited_summary(db_session: AsyncSession):
    """Verify that run_search populates summary in PersonResult with cited claim IDs."""
    name = f"Jane Doe {uuid.uuid4().hex[:6]}"
    url = f"https://tech.corp/team/{uuid.uuid4()}"

    request = SearchRequest(name=name, hints=SearchHints())
    fake_candidates = [CandidateURL(url=url, source_type="company_page", rank=1)]
    fake_sources = [
        CollectedSource(
            url=url,
            domain="tech.corp",
            title="Team",
            source_type="company_page",
            text=f"{name} is a Lead Architect at Tech Corp.",
        )
    ]

    async def mock_extract(*args, **kwargs):
        return [
            {"claim_type": "organization", "value": "Tech Corp", "evidence_span": "Tech Corp"},
            {"claim_type": "occupation", "value": "Lead Architect", "evidence_span": "Lead Architect"},
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

    assert len(response.results) == 1
    person_res = response.results[0]
    assert person_res.summary is not None
    assert len(person_res.summary.sentences) >= 1

    first_sentence = person_res.summary.sentences[0]
    assert len(first_sentence.claim_ids) >= 1
    # Verify cited claim IDs exist in person_res.claims
    all_claim_ids = {c.claim_id for c in person_res.claims}
    for cid in first_sentence.claim_ids:
        assert cid in all_claim_ids


@pytest.mark.asyncio
async def test_persons_api_returns_cited_summary(db_session: AsyncSession):
    """GET /api/v1/persons/{id} returns summary with citations."""
    name = f"Sam Taylor {uuid.uuid4().hex[:6]}"
    person = Person(
        canonical_name=name,
        summary_json={
            "full_text": f"{name} is a Director at Global Inc.",
            "sentences": [
                {
                    "text": f"{name} is a Director at Global Inc.",
                    "claim_ids": [str(uuid.uuid4())],
                }
            ],
        },
    )
    db_session.add(person)
    await db_session.commit()
    await db_session.refresh(person)

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
            assert "summary" in data
            assert data["summary"] is not None
            assert "sentences" in data["summary"]
            assert len(data["summary"]["sentences"]) == 1
            assert "Global Inc" in data["summary"]["sentences"][0]["text"]
    finally:
        app.dependency_overrides.pop(get_db, None)
