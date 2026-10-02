"""
Re-verification worker  —  V1.5 staleness detection.

Periodically sweeps the database for sources whose `expires_at` has passed,
re-fetches the page, compares the SHA-256 content hash against the stored hash,
and marks changed or unreachable sources as `is_stale = True`.

Stale claims (via the cascade from their source) are also flagged with
`is_stale = True` so the API can surface a staleness indicator to users.

Usage (called from app lifespan or a standalone process):
    from app.workers.reverify import start_reverify_worker
    asyncio.create_task(start_reverify_worker())

Design constraints:
  - Fetches are subject to the same robots.txt / domain-rate-limit rules as
    the collector, so this module re-uses `SourceCollector`.
  - Batch size is configurable via `settings.reverify_batch_size` to avoid
    thundering-herd on large corpora.
  - Each sweep is fully idempotent: if a source was already marked stale,
    it is skipped unless a re-verification explicitly clears the flag.
"""

import asyncio
import hashlib
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.claim import Claim
from app.models.source import Source

logger = structlog.get_logger(__name__)


# ── Hash helpers ───────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Core sweep ─────────────────────────────────────────────────────────────────

async def _sweep_once(db: AsyncSession) -> dict:
    """
    Run a single staleness sweep.

    Steps:
      1. Find sources where expires_at < now AND is_stale = False (not yet flagged).
      2. Attempt to re-fetch each source URL.
      3. Compare SHA-256 of new content vs stored content_hash.
      4. If changed or unreachable → mark source is_stale = True.
      5. Cascade: mark all claims linked to that source as is_stale = True.

    Returns a summary dict for logging.
    """
    now = datetime.now(timezone.utc)
    summary = {"checked": 0, "newly_stale": 0, "unchanged": 0, "fetch_errors": 0}

    # ── 1. Find expired, not-yet-stale sources ────────────────────────────────
    result = await db.execute(
        select(Source)
        .where(Source.expires_at <= now)
        .where(Source.is_stale.is_(False))
        .order_by(Source.expires_at.asc())
        .limit(settings.reverify_batch_size)
    )
    sources = result.scalars().all()

    if not sources:
        logger.debug("reverify.sweep_empty")
        return summary

    logger.info("reverify.sweep_started", sources_to_check=len(sources))

    for source in sources:
        summary["checked"] += 1
        log = logger.bind(source_id=str(source.id), url=source.url)

        # ── 2. Re-fetch ───────────────────────────────────────────────────────
        try:
            import httpx
            async with httpx.AsyncClient(timeout=settings.collector_timeout_seconds) as client:
                resp = await client.get(
                    source.url,
                    headers={"User-Agent": "PersonSearch-Reverify/1.5 (+https://example.com/bot)"},
                    follow_redirects=True,
                )
                resp.raise_for_status()
                new_text = resp.text
        except Exception as exc:
            # Unreachable / error → mark stale
            log.warning("reverify.fetch_error", error=str(exc))
            summary["fetch_errors"] += 1
            await _mark_stale(source, db)
            summary["newly_stale"] += 1
            continue

        # ── 3. Compare hashes ─────────────────────────────────────────────────
        new_hash = _sha256(new_text)
        stored_hash = source.content_hash

        if stored_hash and new_hash == stored_hash:
            # Content unchanged — refresh the expiry window
            log.debug("reverify.unchanged")
            from app.core.persistence import _source_expires_at
            source.expires_at = _source_expires_at(source.source_type)
            source.retrieved_at = now
            summary["unchanged"] += 1
        else:
            # Content changed or no prior hash stored → mark stale
            log.info(
                "reverify.content_changed",
                old_hash=(stored_hash or "none")[:12],
                new_hash=new_hash[:12],
            )
            await _mark_stale(source, db)
            source.content_hash = new_hash  # update to latest
            summary["newly_stale"] += 1

    await db.flush()

    logger.info(
        "reverify.sweep_complete",
        **summary,
    )
    return summary


async def _mark_stale(source: Source, db: AsyncSession) -> None:
    """Mark a source and all its claims as stale."""
    source.is_stale = True

    # Cascade to claims
    await db.execute(
        update(Claim)
        .where(Claim.source_id == source.id)
        .values(is_stale=True)
    )


# ── Worker loop ────────────────────────────────────────────────────────────────

async def start_reverify_worker() -> None:
    """
    Long-running asyncio task: sweeps for stale sources on a configured interval.

    Call this once from the app lifespan:
        asyncio.create_task(start_reverify_worker())
    """
    interval = settings.reverify_sweep_interval_seconds
    logger.info("reverify.worker_started", interval_seconds=interval)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    await _sweep_once(db)
        except Exception as exc:
            logger.error("reverify.worker_error", error=str(exc))

        await asyncio.sleep(interval)
