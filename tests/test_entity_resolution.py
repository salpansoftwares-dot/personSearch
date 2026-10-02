"""
Unit and integration tests for Entity Resolution.

Verifies:
  1. Default to unmerged: candidates with the same name but different employers
     are NEVER merged into one profile.
  2. Conflicting employers or occupations trigger a hard veto on merging.
  3. Corroborated sources (shared employer or cross-links or shared identifiers)
     are successfully merged into a single cluster.
  4. run_search produces separate PersonResults for unmerged profiles without
     scrambling or compiling disparate sources into one identity.
"""

import uuid
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.model_adapter import ModelAdapter
from app.core.collector import CollectedSource
from app.core.discovery import CandidateURL
from app.core.entity_resolution import (
    PersonCluster,
    evaluate_pairwise_merge,
    resolve_entities,
)
from app.core.orchestrator import run_search
from app.models.person import Person, PersonClaim
from app.models.claim import Claim
from app.schemas.search import SearchHints, SearchRequest


def test_distinct_employers_stay_unmerged():
    """
    Two candidates with the exact same name but conflicting employers and NO
    cross-links must NEVER be merged into one individual profile.
    """
    candidates = [
        {
            "url": "https://safaricom.co.ke/team/jkamau",
            "name_on_source": "John Kamau",
            "claims": [
                {"claim_type": "organization", "value": "Safaricom PLC", "evidence_span": "Safaricom PLC"},
                {"claim_type": "occupation", "value": "Software Engineer", "evidence_span": "Software Engineer"},
            ],
        },
        {
            "url": "https://knh.or.ke/staff/jkamau",
            "name_on_source": "John Kamau",
            "claims": [
                {"claim_type": "organization", "value": "Kenyatta National Hospital", "evidence_span": "Kenyatta National Hospital"},
                {"claim_type": "occupation", "value": "Pediatric Surgeon", "evidence_span": "Pediatric Surgeon"},
            ],
        },
    ]

    primaries, alternatives = resolve_entities(
        candidate_claim_sets=candidates,
        target_name="John Kamau",
    )

    # Both are valid matches for 'John Kamau', but MUST be kept in separate clusters
    assert len(primaries) == 2, f"Expected 2 separate primary clusters, got {len(primaries)}"
    
    orgs_in_c1 = {c["value"] for c in primaries[0].claims if c.get("claim_type") == "organization"}
    orgs_in_c2 = {c["value"] for c in primaries[1].claims if c.get("claim_type") == "organization"}

    # Cluster 1 must only have Safaricom; Cluster 2 must only have KNH
    assert ("Safaricom PLC" in orgs_in_c1 and "Kenyatta National Hospital" in orgs_in_c2) or \
           ("Safaricom PLC" in orgs_in_c2 and "Kenyatta National Hospital" in orgs_in_c1)
    
    # Must NOT have merged the employers together in either cluster
    assert "Kenyatta National Hospital" not in orgs_in_c1 or "Safaricom PLC" not in orgs_in_c1
    assert "Kenyatta National Hospital" not in orgs_in_c2 or "Safaricom PLC" not in orgs_in_c2


def test_same_employer_merges_sources():
    """
    Two sources about the same person at the same employer should be merged
    together into one single cluster with combined claims.
    """
    candidates = [
        {
            "url": "https://safaricom.co.ke/team/jkamau",
            "name_on_source": "John Kamau",
            "claims": [
                {"claim_type": "organization", "value": "Safaricom", "evidence_span": "at Safaricom"},
                {"claim_type": "occupation", "value": "Software Engineer", "evidence_span": "Software Engineer"},
            ],
        },
        {
            "url": "https://techconference.ke/speakers/jkamau",
            "name_on_source": "John Kamau",
            "claims": [
                {"claim_type": "organization", "value": "Safaricom PLC", "evidence_span": "from Safaricom PLC"},
                {"claim_type": "talk", "value": "Scaling Microservices", "evidence_span": "Scaling Microservices"},
            ],
        },
    ]

    primaries, alternatives = resolve_entities(
        candidate_claim_sets=candidates,
        target_name="John Kamau",
    )

    assert len(primaries) == 1, "Corroborated sources sharing same employer should merge into 1 cluster"
    claim_types = {c["claim_type"] for c in primaries[0].claims}
    assert "occupation" in claim_types
    assert "talk" in claim_types
    assert len(primaries[0].source_urls) == 2


def test_cross_link_merges_sources():
    """
    Two sources that cross-reference each other (e.g. GitHub and personal page)
    should merge via cross_links.
    """
    github_url = "https://github.com/jkamau"
    personal_url = "https://johnkamau.dev"

    c1 = PersonCluster(
        cluster_id="c1",
        canonical_name="John Kamau",
        claims=[
            {"claim_type": "profile_url", "value": personal_url, "evidence_span": personal_url},
            {"claim_type": "project", "value": "OpenSourceLib", "evidence_span": "OpenSourceLib"},
        ],
        source_urls=[github_url],
    )
    c2 = PersonCluster(
        cluster_id="c2",
        canonical_name="John Kamau",
        claims=[
            {"claim_type": "occupation", "value": "Consultant", "evidence_span": "Consultant"},
        ],
        source_urls=[personal_url],
    )

    can_merge, score, signals = evaluate_pairwise_merge(c1, c2)
    assert can_merge is True
    assert signals["cross_links"] == 1.0


class StubAdapter(ModelAdapter):
    async def complete(self, prompt: str, system: str = "") -> str:
        return ""

    async def extract_structured(self, prompt: str, schema: type, system: str = ""):
        return None


@pytest.mark.asyncio
async def test_end_to_end_search_does_not_scramble_profiles(db_session: AsyncSession):
    """
    Search request for a common name with 2 candidates at different companies
    must return 2 distinct PersonResult objects, each with only its own claims.
    """
    name = f"David Miller {uuid.uuid4().hex[:6]}"
    url_tech = f"https://tech.corp/team/{uuid.uuid4()}"
    url_law = f"https://law.chambers/partners/{uuid.uuid4()}"

    request = SearchRequest(name=name, hints=SearchHints())

    fake_candidates = [
        CandidateURL(url=url_tech, source_type="company_page", rank=1),
        CandidateURL(url=url_law, source_type="company_page", rank=2),
    ]
    fake_sources = [
        CollectedSource(url=url_tech, domain="tech.corp", title="Tech Team", source_type="company_page", text="David Miller is a Software Architect at Tech Corp."),
        CollectedSource(url=url_law, domain="law.chambers", title="Legal Team", source_type="company_page", text="David Miller is a Managing Partner at Legal Chambers."),
    ]

    async def mock_extract(*args, **kwargs):
        source_url = kwargs.get("source_url") or (args[0] if args else "")
        if source_url == url_tech:
            return [
                {"claim_type": "organization", "value": "Tech Corp", "evidence_span": "Tech Corp"},
                {"claim_type": "occupation", "value": "Software Architect", "evidence_span": "Software Architect"},
            ]
        else:
            return [
                {"claim_type": "organization", "value": "Legal Chambers", "evidence_span": "Legal Chambers"},
                {"claim_type": "occupation", "value": "Managing Partner", "evidence_span": "Managing Partner"},
            ]

    adapter = StubAdapter()

    with (
        patch("app.core.orchestrator.discover_candidates", new_callable=AsyncMock) as mock_disc,
        patch("app.core.orchestrator.collect_sources", new_callable=AsyncMock) as mock_coll,
        patch("app.core.orchestrator.extract_claims", side_effect=mock_extract),
    ):
        mock_disc.return_value = fake_candidates
        mock_coll.return_value = fake_sources

        response = await run_search(request=request, db=db_session, adapter=adapter)

    # Crucial assertion: Must return 2 separate profiles, NOT 1 compiled profile!
    assert len(response.results) == 2, f"Expected 2 unmerged profiles, got {len(response.results)}"

    p1, p2 = response.results[0], response.results[1]
    assert p1.person_id != p2.person_id

    # Check that alternatives links each profile to the other
    assert p2.person_id in p1.alternatives
    assert p1.person_id in p2.alternatives

    # Check claims are NOT cross-contaminated
    p1_orgs = {c.value for c in p1.claims if c.type == "organization"}
    p2_orgs = {c.value for c in p2.claims if c.type == "organization"}

    assert p1_orgs != p2_orgs
    assert ("Tech Corp" in p1_orgs and "Legal Chambers" in p2_orgs) or \
           ("Tech Corp" in p2_orgs and "Legal Chambers" in p1_orgs)

    # In database, 2 distinct Person records exist
    res = await db_session.execute(select(Person).where(Person.canonical_name == name))
    db_persons = res.scalars().all()
    assert len(db_persons) == 2
