"""
Unit and integration tests for the Claim Persistence module.

Verifies:
  - Source upsert (idempotency, conflict handling)
  - Claim insertion (allowlist validation, deduplication)
  - Person upsert (get-or-create active identity)
  - Person-claim linking (junction with confidence and reason)
  - Person name variant recording
  - Full cluster persistence (single transaction, end-to-end)
  - Suppression enforcement (opt-out list & suppressed person status)
  - Multi-cluster search result persistence
"""

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.collector import CollectedSource
from app.core.entity_resolution import PersonCluster
from app.core.persistence import (
    _suppression_key,
    insert_claim,
    is_suppressed,
    link_person_claim,
    persist_cluster,
    persist_search_results,
    record_person_name,
    upsert_person,
    upsert_source,
)
from app.models.claim import Claim, ClaimType
from app.models.governance import Suppression
from app.models.person import Person, PersonClaim, PersonName, PersonStatus
from app.models.source import Source


@pytest.mark.asyncio
class TestSuppression:
    async def test_unsuppressed_name_returns_false(self, db_session: AsyncSession):
        suppressed = await is_suppressed("Random Name That Does Not Exist", db_session)
        assert suppressed is False

    async def test_suppressed_via_suppression_table(self, db_session: AsyncSession):
        name = "Suppressed Individual Test"
        key = _suppression_key(name)
        db_session.add(Suppression(match_key=key))
        await db_session.flush()

        assert await is_suppressed(name, db_session) is True
        # Case insensitivity check
        assert await is_suppressed("suppressed individual test", db_session) is True

    async def test_suppressed_via_person_status(self, db_session: AsyncSession):
        name = "Jane Optout"
        person = Person(canonical_name=name, status=PersonStatus.suppressed)
        db_session.add(person)
        await db_session.flush()

        assert await is_suppressed(name, db_session) is True


@pytest.mark.asyncio
class TestSourceUpsert:
    async def test_upsert_new_source(self, db_session: AsyncSession):
        test_url = f"https://example.com/company/team/{uuid.uuid4()}"
        source = await upsert_source(
            url=test_url,
            domain="example.com",
            title="Team Page",
            source_type="company_page",
            db=db_session,
        )
        assert source.id is not None
        assert source.url == test_url
        assert source.domain == "example.com"
        assert source.source_type == "company_page"

    async def test_upsert_existing_source_is_idempotent(self, db_session: AsyncSession):
        test_url = f"https://example.com/profiles/{uuid.uuid4()}"
        source1 = await upsert_source(
            url=test_url,
            domain="example.com",
            title="Profile 1",
            source_type="company_page",
            db=db_session,
        )
        source2 = await upsert_source(
            url=test_url,
            domain="example.com",
            title="Profile 2",
            source_type="company_page",
            db=db_session,
        )
        assert source1.id == source2.id


@pytest.mark.asyncio
class TestClaimInsertion:
    async def test_insert_valid_claim(self, db_session: AsyncSession):
        test_url = f"https://example.com/user/{uuid.uuid4()}"
        source = await upsert_source(
            url=test_url,
            domain="example.com",
            title="User Bio",
            source_type="linkedin_profile",
            db=db_session,
        )
        claim = await insert_claim(
            source=source,
            claim_type="occupation",
            value="Principal Engineer",
            evidence_span="Principal Engineer at Acme",
            confidence=0.95,
            db=db_session,
        )
        assert claim is not None
        assert claim.id is not None
        assert claim.source_id == source.id
        assert claim.claim_type == "occupation"
        assert claim.value == "Principal Engineer"
        assert claim.confidence == 0.95

    async def test_insert_invalid_claim_type_rejected(self, db_session: AsyncSession):
        test_url = f"https://example.com/user/{uuid.uuid4()}"
        source = await upsert_source(
            url=test_url,
            domain="example.com",
            title="Out of scope",
            source_type="company_page",
            db=db_session,
        )
        # home_address is strictly forbidden by the ClaimType enum
        claim = await insert_claim(
            source=source,
            claim_type="home_address",
            value="123 Private St",
            evidence_span="lives at 123 Private St",
            confidence=0.9,
            db=db_session,
        )
        assert claim is None

    async def test_insert_identical_claim_reused(self, db_session: AsyncSession):
        test_url = f"https://example.com/pub/{uuid.uuid4()}"
        source = await upsert_source(
            url=test_url,
            domain="example.com",
            title="Publication",
            source_type="conference",
            db=db_session,
        )
        claim1 = await insert_claim(
            source=source,
            claim_type="publication",
            value="Paper Title 2026",
            evidence_span="Authored Paper Title 2026",
            confidence=0.88,
            db=db_session,
        )
        claim2 = await insert_claim(
            source=source,
            claim_type="publication",
            value="Paper Title 2026",
            evidence_span="Authored Paper Title 2026",
            confidence=0.88,
            db=db_session,
        )
        assert claim1 is not None and claim2 is not None
        assert claim1.id == claim2.id


@pytest.mark.asyncio
class TestPersonAndLinks:
    async def test_upsert_person_and_reuse(self, db_session: AsyncSession):
        unique_name = f"Alex Mercer {uuid.uuid4().hex[:6]}"
        person1 = await upsert_person(canonical_name=unique_name, db=db_session)
        assert person1.id is not None
        assert person1.canonical_name == unique_name

        person2 = await upsert_person(canonical_name=unique_name, db=db_session)
        assert person1.id == person2.id

    async def test_link_person_claim(self, db_session: AsyncSession):
        unique_name = f"Dana Scully {uuid.uuid4().hex[:6]}"
        person = await upsert_person(canonical_name=unique_name, db=db_session)

        source = await upsert_source(
            url=f"https://fbi.gov/agents/{uuid.uuid4()}",
            domain="fbi.gov",
            title="Special Agent",
            source_type="company_page",
            db=db_session,
        )
        claim = await insert_claim(
            source=source,
            claim_type="role",
            value="Special Agent",
            evidence_span="Dana is a Special Agent",
            confidence=0.99,
            db=db_session,
        )
        assert claim is not None

        await link_person_claim(
            person=person,
            claim=claim,
            link_confidence=0.92,
            link_reason="cluster_score=0.920",
            db=db_session,
        )

        res = await db_session.execute(
            select(PersonClaim).where(
                PersonClaim.person_id == person.id,
                PersonClaim.claim_id == claim.id,
            )
        )
        link = res.scalar_one_or_none()
        assert link is not None
        assert link.link_confidence == 0.92
        assert link.link_reason == "cluster_score=0.920"

        # Calling again should not fail
        await link_person_claim(
            person=person,
            claim=claim,
            link_confidence=0.92,
            link_reason="cluster_score=0.920",
            db=db_session,
        )

    async def test_record_person_name(self, db_session: AsyncSession):
        unique_name = f"Jonathan Doe {uuid.uuid4().hex[:6]}"
        person = await upsert_person(canonical_name=unique_name, db=db_session)

        await record_person_name(person=person, name=unique_name, claim=None, db=db_session)
        await record_person_name(person=person, name="John Doe", claim=None, db=db_session)

        res = await db_session.execute(
            select(PersonName).where(PersonName.person_id == person.id)
        )
        names = {pn.name for pn in res.scalars()}
        assert unique_name in names
        assert "John Doe" in names


@pytest.mark.asyncio
class TestPersistCluster:
    async def test_persist_cluster_full_flow(self, db_session: AsyncSession):
        name = f"Alice Researcher {uuid.uuid4().hex[:6]}"
        url = f"https://research.org/staff/{uuid.uuid4()}"
        collected_source = CollectedSource(
            url=url,
            domain="research.org",
            title="Alice Researcher Page",
            source_type="company_page",
            text="Alice Researcher is a Senior Scientist at Research Corp.",
        )

        cluster = PersonCluster(
            cluster_id="cluster-alice-1",
            canonical_name=name,
            claims=[
                {
                    "source_url": url,
                    "source_type": "company_page",
                    "claim_type": "role",
                    "value": "Senior Scientist",
                    "evidence_span": "Senior Scientist at Research Corp.",
                    "confidence": 0.95,
                },
                {
                    "source_url": url,
                    "source_type": "company_page",
                    "claim_type": "organization",
                    "value": "Research Corp",
                    "evidence_span": "Senior Scientist at Research Corp.",
                    "confidence": 0.95,
                },
            ],
            source_urls=[url],
            score=0.88,
        )

        person = await persist_cluster(
            cluster=cluster,
            collected_sources={url: collected_source},
            db=db_session,
        )

        assert person is not None
        assert cluster.person_id == person.id
        assert all("claim_id" in c for c in cluster.claims)

        # Verify DB state
        claims_res = await db_session.execute(
            select(Claim).join(PersonClaim).where(PersonClaim.person_id == person.id)
        )
        db_claims = claims_res.scalars().all()
        assert len(db_claims) == 2
        claim_values = {c.value for c in db_claims}
        assert "Senior Scientist" in claim_values
        assert "Research Corp" in claim_values

    async def test_persist_suppressed_cluster_skipped(self, db_session: AsyncSession):
        name = f"Suppressed Cluster {uuid.uuid4().hex[:6]}"
        key = _suppression_key(name)
        db_session.add(Suppression(match_key=key))
        await db_session.flush()

        cluster = PersonCluster(
            cluster_id="cluster-suppressed",
            canonical_name=name,
            claims=[],
            source_urls=[],
            score=0.9,
        )

        person = await persist_cluster(
            cluster=cluster,
            collected_sources={},
            db=db_session,
        )
        assert person is None
        assert cluster.person_id is None

    async def test_persist_search_results_multiple_clusters(self, db_session: AsyncSession):
        name1 = f"Cluster One {uuid.uuid4().hex[:6]}"
        name2 = f"Cluster Two {uuid.uuid4().hex[:6]}"
        url1 = f"https://example.com/one/{uuid.uuid4()}"
        url2 = f"https://example.com/two/{uuid.uuid4()}"

        cs1 = CollectedSource(
            url=url1,
            domain="example.com",
            title="One",
            source_type="company_page",
            text="...",
        )
        cs2 = CollectedSource(
            url=url2,
            domain="example.com",
            title="Two",
            source_type="company_page",
            text="...",
        )

        c1 = PersonCluster(
            cluster_id="c1",
            canonical_name=name1,
            claims=[{"source_url": url1, "claim_type": "occupation", "value": "Dev"}],
            source_urls=[url1],
            score=0.8,
        )
        c2 = PersonCluster(
            cluster_id="c2",
            canonical_name=name2,
            claims=[{"source_url": url2, "claim_type": "occupation", "value": "Designer"}],
            source_urls=[url2],
            score=0.85,
        )

        persons = await persist_search_results(
            clusters=[c1, c2],
            collected_sources={url1: cs1, url2: cs2},
            db=db_session,
        )
        assert len(persons) == 2
        names = {p.canonical_name for p in persons}
        assert name1 in names
        assert name2 in names
