"""
Policy layer — authentication, rate limiting, and audit helpers.

This module provides FastAPI dependencies that sit in front of every
protected endpoint. The policy layer is the first thing after the
network — no business logic runs until these checks pass.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import time
import uuid

import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

logger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)

# Optional redis client
_redis_client = None


def get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception as exc:
            logger.warning("policy.redis.init_failed", error=str(exc))
            _redis_client = None
    return _redis_client


# In-memory sliding window fallback if Redis is unavailable
_memory_windows: dict[str, list[float]] = defaultdict(list)


# ── JWT Auth Helpers ──────────────────────────────────────────────────────────

def create_access_token(
    user_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a signed JWT access token for a given user."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str | None:
    """
    Extract and validate a bearer JWT token.

    Returns the user_id string, or None for anonymous requests.
    """
    if credentials is None:
        return None  # anonymous — allowed in dev / public search

    token = credentials.credentials
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject claim.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Rate Limit Dependency ──────────────────────────────────────────────────────

async def check_rate_limit(
    request: Request,
    user_id: str | None = Depends(get_current_user),
) -> None:
    """
    Enforce per-user (or per-IP for anonymous) rate limits using a sliding window.
    """
    identifier = user_id or (request.client.host if request.client else "anonymous")
    key = f"rl:{identifier}"
    window_seconds = 60
    limit = settings.rate_limit_searches_per_minute
    now = time.time()

    redis_conn = get_redis()
    if redis_conn is not None:
        try:
            pipe = redis_conn.pipeline()
            pipe.zremrangebyscore(key, 0, now - window_seconds)
            pipe.zadd(key, {str(uuid.uuid4()): now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds + 5)
            results = await pipe.execute()
            request_count = results[2]

            if request_count > limit:
                logger.warning(
                    "rate_limit.exceeded",
                    identifier=identifier,
                    count=request_count,
                    limit=limit,
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please wait before making more requests.",
                    headers={"Retry-After": str(window_seconds)},
                )
            return
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("rate_limit.redis_failed_falling_back", error=str(exc))

    # In-memory sliding window fallback
    timestamps = _memory_windows[key]
    # Prune old timestamps
    cutoff = now - window_seconds
    _memory_windows[key] = [ts for ts in timestamps if ts > cutoff]
    _memory_windows[key].append(now)

    if len(_memory_windows[key]) > limit:
        logger.warning(
            "rate_limit.memory.exceeded",
            identifier=identifier,
            count=len(_memory_windows[key]),
            limit=limit,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please wait before making more requests.",
            headers={"Retry-After": str(window_seconds)},
        )


# ── Purpose Capture Dependency ─────────────────────────────────────────────────

async def require_purpose(purpose: str | None) -> str | None:
    """
    In production, you may require a stated purpose before a search runs.
    Currently advisory — warn but don't block.
    """
    if not purpose:
        logger.warning("policy.purpose_not_stated")
    return purpose
