"""
Tests for Saved Searches API endpoints: /api/v1/saved-searches
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import app
from app.models.saved_search import SavedSearch


@pytest.mark.asyncio
async def test_create_saved_search(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "label": "AI Researchers in Kenya",
            "query": {
                "name": "Jane Doe",
                "hints": {
                    "role": "Research Scientist",
                    "country": "KE",
                },
                "purpose": "Hiring background check",
            },
            "user_id": "user-test-123",
        }
        resp = await client.post("/api/v1/saved-searches", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "AI Researchers in Kenya"
        assert data["user_id"] == "user-test-123"
        assert data["query_json"]["name"] == "Jane Doe"
        assert data["query_json"]["hints"]["country"] == "KE"
        assert "id" in data
        assert "created_at" in data

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_and_filter_saved_searches(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    user_a = f"user-{uuid.uuid4()}"
    user_b = f"user-{uuid.uuid4()}"

    s1 = SavedSearch(
        label="Search A1",
        query_json={"name": "Alice Smith"},
        user_id=user_a,
    )
    s2 = SavedSearch(
        label="Search A2",
        query_json={"name": "Bob Jones"},
        user_id=user_a,
    )
    s3 = SavedSearch(
        label="Search B1",
        query_json={"name": "Charlie Brown"},
        user_id=user_b,
    )
    db_session.add_all([s1, s2, s3])
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Filter by user_a
        resp = await client.get(f"/api/v1/saved-searches?user_id={user_a}")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        labels = [item["label"] for item in items]
        assert "Search A1" in labels
        assert "Search A2" in labels

        # Filter by user_b
        resp = await client.get(f"/api/v1/saved-searches?user_id={user_b}")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["label"] == "Search B1"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_saved_search_by_id(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    saved = SavedSearch(
        label="Specialist Query",
        query_json={"name": "Dr. Grace Hopper", "hints": {"role": "Computer Scientist"}},
        user_id="user-xyz",
    )
    db_session.add(saved)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Success
        resp = await client.get(f"/api/v1/saved-searches/{saved.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(saved.id)
        assert resp.json()["label"] == "Specialist Query"

        # Not found
        random_id = uuid.uuid4()
        resp_404 = await client.get(f"/api/v1/saved-searches/{random_id}")
        assert resp_404.status_code == 404

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_saved_search(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    saved = SavedSearch(
        label="Initial Label",
        query_json={"name": "Initial Name"},
        user_id="user-edit",
    )
    db_session.add(saved)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        patch_payload = {
            "label": "Updated Label",
            "query": {"name": "Updated Name", "hints": {"country": "US"}},
        }
        resp = await client.patch(f"/api/v1/saved-searches/{saved.id}", json=patch_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "Updated Label"
        assert data["query_json"]["name"] == "Updated Name"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_saved_search(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    saved = SavedSearch(
        label="To Delete",
        query_json={"name": "Delete Me"},
        user_id="user-del",
    )
    db_session.add(saved)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Delete
        resp = await client.delete(f"/api/v1/saved-searches/{saved.id}")
        assert resp.status_code == 204

        # Verify 404 after deletion
        resp_check = await client.get(f"/api/v1/saved-searches/{saved.id}")
        assert resp_check.status_code == 404

    app.dependency_overrides.clear()


from unittest.mock import AsyncMock, patch
from app.schemas.search import SearchResponse


@pytest.mark.asyncio
async def test_execute_saved_search(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session

    saved = SavedSearch(
        label="Execute Test",
        query_json={"name": "Ada Lovelace", "hints": {"role": "Mathematician"}},
        user_id="exec-user",
    )
    db_session.add(saved)
    await db_session.flush()

    mock_resp = SearchResponse(
        query_id=uuid.uuid4(),
        results=[],
        parsed_hints={"role": "Mathematician"},
    )

    with patch("app.api.v1.saved_searches.run_search", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_resp
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/v1/saved-searches/{saved.id}/execute")
            assert resp.status_code == 200
            data = resp.json()
            assert "query_id" in data
            assert "results" in data
            assert mock_run.await_count == 1
            call_kwargs = mock_run.await_args.kwargs
            assert call_kwargs["request"].name == "Ada Lovelace"

    app.dependency_overrides.clear()



@pytest.mark.asyncio
async def test_execute_saved_search_not_found(db_session: AsyncSession):
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/saved-searches/{uuid.uuid4()}/execute")
        assert resp.status_code == 404

    app.dependency_overrides.clear()
