"""
Tests for Exportable Evidence Reports endpoint: GET /api/v1/persons/{person_id}/report
"""

import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import app
from app.models.claim import Claim, ClaimType
from app.models.person import Person, PersonClaim, PersonStatus
from app.models.source import Source


@pytest.mark.asyncio
async def test_get_evidence_report_json(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    # 1. Setup Person
    person = Person(canonical_name="Alan Turing", status=PersonStatus.active)
    db_session.add(person)
    await db_session.flush()

    # 2. Setup Sources
    source1 = Source(
        url=f"https://cam.ac.uk/fellows/{uuid.uuid4()}",
        domain="cam.ac.uk",
        title="Cambridge Archives",
        source_type="university_page",
        retrieved_at=datetime.now(timezone.utc),
    )
    source2 = Source(
        url=f"https://bletchleypark.org.uk/researchers/{uuid.uuid4()}",
        domain="bletchleypark.org.uk",
        title="Bletchley Park Roll of Honour",
        source_type="registry",
        retrieved_at=datetime.now(timezone.utc),
    )
    db_session.add_all([source1, source2])
    await db_session.flush()

    # 3. Setup Claims
    claim1 = Claim(
        claim_type=ClaimType.occupation,
        value="Mathematician and Cryptanalyst",
        confidence=0.98,
        source_id=source1.id,
        evidence_span="Alan Turing was an English mathematician and cryptanalyst.",
    )
    claim2 = Claim(
        claim_type=ClaimType.organization,
        value="Bletchley Park",
        confidence=0.95,
        source_id=source2.id,
        evidence_span="Worked at the Government Code and Cypher School at Bletchley Park.",
    )
    db_session.add_all([claim1, claim2])
    await db_session.flush()

    # 4. Link Person to Claims
    pc1 = PersonClaim(person_id=person.id, claim_id=claim1.id, link_confidence=0.98)
    pc2 = PersonClaim(person_id=person.id, claim_id=claim2.id, link_confidence=0.95)
    db_session.add_all([pc1, pc2])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Default JSON format
        resp = await client.get(f"/api/v1/persons/{person.id}/report")
        assert resp.status_code == 200
        data = resp.json()

        assert data["person_id"] == str(person.id)
        assert data["canonical_name"] == "Alan Turing"
        assert data["claims_count"] == 2
        assert data["unique_sources_count"] == 2
        assert "sha256_integrity_hash" in data
        assert len(data["sha256_integrity_hash"]) == 64
        assert "Possible match only" in data["disclaimer"]
        assert len(data["claims"]) == 2

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_evidence_report_csv(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    person = Person(canonical_name="Marie Curie", status=PersonStatus.active)
    db_session.add(person)
    await db_session.flush()

    source = Source(
        url=f"https://nobelprize.org/laureates/{uuid.uuid4()}",
        domain="nobelprize.org",
        title="Nobel Prize Archives",
        source_type="registry",
        retrieved_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.flush()

    claim = Claim(
        claim_type=ClaimType.publication,
        value="Recherches sur les substances radioactives",
        confidence=0.99,
        source_id=source.id,
        evidence_span="Doctoral thesis on radioactive substances.",
    )
    db_session.add(claim)
    await db_session.flush()

    pc = PersonClaim(person_id=person.id, claim_id=claim.id, link_confidence=0.99)
    db_session.add(pc)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/persons/{person.id}/report?format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert f'attachment; filename="evidence_report_{person.id}.csv"' in resp.headers["content-disposition"]

        csv_text = resp.text
        assert "Person ID,Canonical Name,Claim ID,Claim Type" in csv_text
        assert "Marie Curie" in csv_text
        assert "Recherches sur les substances radioactives" in csv_text
        assert "nobelprize.org" in csv_text

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_evidence_report_html(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    person = Person(canonical_name="Rosalind Franklin", status=PersonStatus.active)
    db_session.add(person)
    await db_session.flush()

    source = Source(
        url=f"https://kcl.ac.uk/archives/{uuid.uuid4()}",
        domain="kcl.ac.uk",
        title="King's College Archives",
        source_type="university_page",
        retrieved_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.flush()

    claim = Claim(
        claim_type=ClaimType.occupation,
        value="Chemist and X-ray Crystallographer",
        confidence=0.96,
        source_id=source.id,
        evidence_span="Rosalind Franklin was a chemist and X-ray crystallographer at King's College London.",
    )
    db_session.add(claim)
    await db_session.flush()

    pc = PersonClaim(person_id=person.id, claim_id=claim.id, link_confidence=0.96)
    db_session.add(pc)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/persons/{person.id}/report?format=html")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

        html_text = resp.text
        assert "<!DOCTYPE html>" in html_text
        assert "Rosalind Franklin" in html_text
        assert "Chemist and X-ray Crystallographer" in html_text
        assert "SHA-256 Provenance Checksum" in html_text
        assert "POSSIBLE MATCH ONLY" in html_text

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_evidence_report_not_found(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        random_id = uuid.uuid4()
        resp = await client.get(f"/api/v1/persons/{random_id}/report")
        assert resp.status_code == 404

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_evidence_report_suppressed_returns_404(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    person = Person(canonical_name="Suppressed Subject", status=PersonStatus.suppressed)
    db_session.add(person)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/persons/{person.id}/report")
        assert resp.status_code == 404

    app.dependency_overrides.clear()
