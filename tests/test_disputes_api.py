"""
Tests for Disputes API endpoint: POST /api/v1/disputes
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import app
from app.models.person import Person, PersonStatus


@pytest.mark.asyncio
async def test_submit_dispute_requires_person_or_claim():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/disputes/",
            json={"submitter": "anonymous@example.com", "reason": "No id given"},
        )
        assert resp.status_code == 422
        assert "Either person_id or claim_id must be provided" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_submit_dispute_nonexistent_person_returns_404(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    fake_id = uuid.uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/disputes/",
            json={"person_id": str(fake_id), "submitter": "subject@example.com", "reason": "Not me"},
        )
        assert resp.status_code == 404
        assert f"Person {fake_id} not found" in resp.json()["detail"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_submit_dispute_success(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    person = Person(canonical_name="Alan Turing", status=PersonStatus.active)
    db_session.add(person)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/disputes/",
            json={
                "person_id": str(person.id),
                "submitter": "representative@turing.org",
                "reason": "Please update bio",
            },
        )
        assert resp.status_code == 201
        data = resp.json()

        assert "dispute_id" in data
        assert data["status"] == "open"
        assert "received and will be reviewed" in data["message"]

    app.dependency_overrides.clear()
