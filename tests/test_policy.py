"""
Tests for Policy Layer: JWT authentication and Rate Limiting
"""

from datetime import timedelta
import uuid
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.policy import (
    _memory_windows,
    check_rate_limit,
    create_access_token,
    get_current_user,
)


@pytest.mark.asyncio
class TestJWTAuth:
    async def test_valid_token_returns_user_id(self):
        token = create_access_token("analyst_99")

        class MockCreds:
            credentials = token

        user = await get_current_user(MockCreds())
        assert user == "analyst_99"

    async def test_expired_token_raises_401(self):
        token = create_access_token("analyst_99", expires_delta=timedelta(seconds=-10))

        class MockCreds:
            credentials = token

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(MockCreds())
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    async def test_invalid_token_raises_401(self):
        class MockCreds:
            credentials = "not.a.valid.jwt"

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(MockCreds())
        assert exc_info.value.status_code == 401

    async def test_anonymous_returns_none(self):
        user = await get_current_user(None)
        assert user is None


@pytest.mark.asyncio
class TestRateLimiter:
    async def test_rate_limit_enforced_when_exceeded(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "rate_limit_searches_per_minute", 3)

        # Clear in-memory windows
        _memory_windows.clear()

        # Mock request
        scope = {"type": "http", "client": ("192.168.1.100", 12345), "path": "/api/v1/search"}
        request = Request(scope)

        test_uid = f"test_user_{uuid.uuid4().hex}"

        # First 3 requests should pass
        await check_rate_limit(request, user_id=test_uid)
        await check_rate_limit(request, user_id=test_uid)
        await check_rate_limit(request, user_id=test_uid)

        # 4th request should raise 429
        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(request, user_id=test_uid)

        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in exc_info.value.detail
