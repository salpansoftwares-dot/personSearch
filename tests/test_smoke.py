"""
Basic smoke tests — verify the app can be imported and the API structure
is correct without needing a running database.
"""

import pytest
from fastapi.testclient import TestClient


def test_app_import() -> None:
    """The app must be importable with no external services running."""
    from app.main import app  # noqa: F401


def test_health_endpoint() -> None:
    from app.main import app
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_search_request_validation() -> None:
    """Search with a too-short name should return 422."""
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/v1/search", json={"name": "A"})
    assert response.status_code == 422


def test_scope_filter_drops_out_of_scope() -> None:
    from app.core.scope_filter import filter_claims
    claims = [
        {"claim_type": "occupation", "value": "Engineer"},
        {"claim_type": "home_address", "value": "123 Main St"},  # out of scope
        {"claim_type": "organization", "value": "Acme Ltd"},
    ]
    result = filter_claims(claims)
    types = [c["claim_type"] for c in result]
    assert "home_address" not in types
    assert "occupation" in types
    assert "organization" in types


def test_entity_resolution_conservative_merge() -> None:
    """A weak name-only match should NOT exceed the merge threshold."""
    from app.core.entity_resolution import resolve_entities
    candidates = [
        {
            "url": "https://example.com/profile/john-kamau",
            "name_on_source": "John Mwangi",  # different middle name
            "claims": [{"claim_type": "occupation", "value": "Engineer"}],
        }
    ]
    primaries, alternatives = resolve_entities(
        candidate_claim_sets=candidates,
        target_name="John Kamau",
        merge_threshold=0.75,
    )
    # A name-only weak match should stay in alternatives
    assert len(primaries) == 0
    assert len(alternatives) == 1
