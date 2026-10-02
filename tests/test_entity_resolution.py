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


# ── V2 Feature 2 Tests: Cross-links, Identifiers, Embeddings, Explanations ─────

def test_normalize_url():
    from app.core.entity_resolution import _normalize_url
    assert _normalize_url("https://www.linkedin.com/in/alice/") == "linkedin.com/in/alice"
    assert _normalize_url("http://github.com/alice?tab=repositories#header") == "github.com/alice"
    assert _normalize_url("https://sub.domain.org/path/") == "sub.domain.org/path"


def test_cross_link_variations():
    """Verify bidirectional cross-link detection across query params and trailing slashes."""
    from app.core.entity_resolution import _has_cross_link, PersonCluster

    c1 = PersonCluster(
        cluster_id="c1",
        canonical_name="Jane Doe",
        claims=[
            {
                "claim_type": "profile_url",
                "value": "https://www.github.com/janedoe?tab=overview",
                "evidence_span": "GitHub: https://github.com/janedoe",
            }
        ],
        source_urls=["https://janedoe.com"],
    )
    c2 = PersonCluster(
        cluster_id="c2",
        canonical_name="Jane Doe",
        claims=[
            {"claim_type": "occupation", "value": "Developer", "evidence_span": "Developer"}
        ],
        source_urls=["https://github.com/janedoe/"],
    )

    assert _has_cross_link(c1, c2) is True
    assert _has_cross_link(c2, c1) is True


def test_orcid_shared_identifier():
    """ORCID iDs appearing in evidence spans or claims act as strong shared identifiers."""
    from app.core.entity_resolution import _has_shared_identifier, evaluate_pairwise_merge, PersonCluster

    c1 = PersonCluster(
        cluster_id="c1",
        canonical_name="Dr. Alice Smith",
        claims=[
            {
                "claim_type": "publication",
                "value": "Quantum Computing",
                "evidence_span": "Author ORCID: 0000-0002-1825-0097",
            }
        ],
        source_urls=["https://arxiv.org/abs/1234.5678"],
    )
    c2 = PersonCluster(
        cluster_id="c2",
        canonical_name="Alice Smith",
        claims=[
            {
                "claim_type": "education",
                "value": "PhD Physics",
                "evidence_span": "ORCID record 0000-0002-1825-0097 verified",
            }
        ],
        source_urls=["https://orcid.org/0000-0002-1825-0097"],
    )

    assert _has_shared_identifier(c1, c2) is True
    can_merge, score, signals = evaluate_pairwise_merge(c1, c2)
    assert can_merge is True
    assert signals["shared_identifier"] == 1.0


def test_sector_matching_and_conflict():
    """Test sector classification and conflict detection between profession buckets."""
    from app.core.entity_resolution import _compare_sectors, PersonCluster

    c_tech = PersonCluster(
        cluster_id="c_tech",
        canonical_name="Alex",
        claims=[{"claim_type": "occupation", "value": "Software Engineer"}],
    )
    c_tech2 = PersonCluster(
        cluster_id="c_tech2",
        canonical_name="Alex",
        claims=[{"claim_type": "occupation", "value": "DevOps Architect"}],
    )
    c_med = PersonCluster(
        cluster_id="c_med",
        canonical_name="Alex",
        claims=[{"claim_type": "occupation", "value": "Pediatric Surgeon"}],
    )

    same_sec, conflict = _compare_sectors(c_tech, c_tech2)
    assert same_sec is True
    assert conflict is False

    same_sec_diff, conflict_diff = _compare_sectors(c_tech, c_med)
    assert same_sec_diff is False
    assert conflict_diff is True


def test_profile_description_builder():
    """Verify build_profile_description synthesizes a concise textual representation."""
    from app.core.entity_resolution import build_profile_description, PersonCluster

    cluster = PersonCluster(
        cluster_id="c1",
        canonical_name="David Kim",
        claims=[
            {"claim_type": "occupation", "value": "Lead Architect"},
            {"claim_type": "organization", "value": "Acme Tech"},
            {"claim_type": "education", "value": "BSc Computer Science"},
            {"claim_type": "publication", "value": "Distributed Systems at Scale"},
        ],
    )

    desc = build_profile_description(cluster)
    assert "David Kim" in desc
    assert "Lead Architect" in desc
    assert "Acme Tech" in desc
    assert "BSc Computer Science" in desc
    assert "Distributed Systems at Scale" in desc


def test_profile_similarity():
    """Verify similarity is high for matching domains and low for divergent domains."""
    from app.core.entity_resolution import compute_profile_similarity, PersonCluster

    c1 = PersonCluster(
        cluster_id="c1",
        canonical_name="David Kim",
        claims=[
            {"claim_type": "occupation", "value": "Software Architect"},
            {"claim_type": "organization", "value": "Cloud Systems"},
            {"claim_type": "project", "value": "Distributed Cache"},
        ],
    )
    c2 = PersonCluster(
        cluster_id="c2",
        canonical_name="David Kim",
        claims=[
            {"claim_type": "occupation", "value": "Senior Software Architect"},
            {"claim_type": "organization", "value": "Cloud Systems"},
            {"claim_type": "project", "value": "Cloud Infrastructure"},
        ],
    )
    c3 = PersonCluster(
        cluster_id="c3",
        canonical_name="David Kim",
        claims=[
            {"claim_type": "occupation", "value": "Pediatric Nurse"},
            {"claim_type": "organization", "value": "City Children Hospital"},
        ],
    )

    sim_similar = compute_profile_similarity(c1, c2)
    sim_different = compute_profile_similarity(c1, c3)

    assert sim_similar > 0.50
    assert sim_different < 0.25
    assert sim_similar > sim_different


def test_borderline_explanation_generation():
    """Verify explain_borderline_pair produces clear plain-language rationale."""
    from app.core.entity_resolution import evaluate_pairwise_merge, PersonCluster

    # Case 1: Conflicting employers
    c1 = PersonCluster(
        cluster_id="c1",
        canonical_name="John Kamau",
        claims=[
            {"claim_type": "organization", "value": "Safaricom PLC"},
            {"claim_type": "occupation", "value": "Software Engineer"},
        ],
    )
    c2 = PersonCluster(
        cluster_id="c2",
        canonical_name="John Kamau",
        claims=[
            {"claim_type": "organization", "value": "Kenya Power"},
            {"claim_type": "occupation", "value": "Electrical Engineer"},
        ],
    )

    can_merge, score, signals = evaluate_pairwise_merge(c1, c2)
    assert can_merge is False
    explanation = signals.get("borderline_explanation", "")
    assert "Kept separate" in explanation
    assert "conflicting organizations" in explanation.lower() or "conflict" in explanation.lower()


def test_embedding_similarity_does_not_override_hard_veto():
    """
    Architecture rule:
    AI proposes, deterministic code decides. High embedding similarity between
    two profile descriptions must NEVER override hard employer or sector conflict vetoes.
    """
    from app.core.entity_resolution import evaluate_pairwise_merge, PersonCluster

    # Two people with very similar skill descriptions but DIFFERENT employers and NO cross-links
    c1 = PersonCluster(
        cluster_id="c1",
        canonical_name="Sarah Connor",
        claims=[
            {"claim_type": "occupation", "value": "Security Specialist"},
            {"claim_type": "organization", "value": "Cyberdyne Systems"},
            {"claim_type": "project", "value": "Defensive Perimeter Audit"},
        ],
    )
    c2 = PersonCluster(
        cluster_id="c2",
        canonical_name="Sarah Connor",
        claims=[
            {"claim_type": "occupation", "value": "Security Specialist"},
            {"claim_type": "organization", "value": "Resistance HQ"},
            {"claim_type": "project", "value": "Defensive Perimeter Audit"},
        ],
    )

    can_merge, score, signals = evaluate_pairwise_merge(c1, c2)
    assert can_merge is False, "Different employers without cross-links must veto merge despite high similarity"
    assert signals.get("employer_conflict") == 1.0


@pytest.mark.asyncio
async def test_model_adapter_embed_nvidia_mock():
    """Test ModelAdapter embed method with mocked API response."""
    import respx
    import httpx
    from app.core.ai.model_adapter import ModelAdapter

    adapter = ModelAdapter()
    if adapter._provider != "nvidia":
        pytest.skip("NVIDIA provider test only")

    with respx.mock(base_url="https://integrate.api.nvidia.com/v1") as respx_mock:
        respx_mock.post("/embeddings").respond(
            status_code=200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ]
            },
        )
        embeddings = await adapter.embed(["Text 1", "Text 2"])
        assert len(embeddings) == 2
        assert embeddings[0] == [0.1, 0.2, 0.3]
        assert embeddings[1] == [0.4, 0.5, 0.6]
