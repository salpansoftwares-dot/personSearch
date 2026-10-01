"""
Tests for Persons API endpoint: GET /api/v1/persons/{person_id}
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
async def test_get_person_not_found(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        random_id = uuid.uuid4()
        resp = await client.get(f"/api/v1/persons/{random_id}")
        assert resp.status_code == 404
        assert f"Person {random_id} not found" in resp.json()["detail"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_person_suppressed_returns_404(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    person = Person(canonical_name="Suppressed Subject", status=PersonStatus.suppressed)
    db_session.add(person)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/persons/{person.id}")
        assert resp.status_code == 404

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_person_success_with_evidence(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    # 1. Setup Person
    person = Person(canonical_name="Katherine Johnson", status=PersonStatus.active)
    db_session.add(person)
    await db_session.flush()

    # 2. Setup Source
    source = Source(
        url=f"https://nasa.gov/bios/{uuid.uuid4()}",
        domain="nasa.gov",
        title="NASA Biography",
        source_type="company_page",
        retrieved_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.flush()

    # 3. Setup Claim
    claim = Claim(
        source_id=source.id,
        claim_type=ClaimType.occupation,
        value="Aerospace Mathematician",
        evidence_span="worked as an Aerospace Mathematician at NASA",
        confidence=0.99,
    )
    db_session.add(claim)
    await db_session.flush()

    # 4. Setup Junction Link
    link = PersonClaim(
        person_id=person.id,
        claim_id=claim.id,
        link_confidence=0.97,
        link_reason="cluster_score=0.970",
    )
    db_session.add(link)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/persons/{person.id}")
        assert resp.status_code == 200
        data = resp.json()

    assert data["person_id"] == str(person.id)
    assert data["canonical_name"] == "Katherine Johnson"
    assert data["status"] == "active"
    assert len(data["claims"]) == 1

    claim_out = data["claims"][0]
    assert claim_out["claim_id"] == str(claim.id)
    assert claim_out["type"] == "occupation"
    assert claim_out["value"] == "Aerospace Mathematician"
    assert claim_out["confidence"] == 0.97
    assert len(claim_out["evidence"]) == 1

    ev = claim_out["evidence"][0]
    assert ev["source_url"] == source.url
    assert ev["source_type"] == "company_page"
    assert ev["excerpt"] == "worked as an Aerospace Mathematician at NASA"
    assert "retrieved_at" in ev

    app.dependency_overrides.clear()
