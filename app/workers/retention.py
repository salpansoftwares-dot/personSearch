"""
Retention sweep worker  —  V1.5 retention policies.

Sweeps the database periodically for claims whose `expires_at` has passed
and marks them as `is_stale = True`. This enforces the "no permanent shadow
database" governance principle.

Claims are NOT deleted outright — they are flagged so operators can review
before hard deletion via a separate admin action. This preserves auditability.

Usage:
    from app.workers.retention import start_retention_worker
    asyncio.create_task(start_retention_worker())
"""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select, update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.claim import Claim

logger = structlog.get_logger(__name__)


async def _retention_sweep_once(db) -> dict:
    """
    Flag all claims whose expires_at has passed as is_stale = True.

    Returns a summary dict for logging.
    """
    now = datetime.now(timezone.utc)

    # Count how many will be swept
    count_res = await db.execute(
        select(func.count())
        .select_from(Claim)
        .where(Claim.expires_at <= now)
        .where(Claim.is_stale.is_(False))
    )
    count = count_res.scalar_one()

    if count == 0:
        logger.debug("retention.sweep_empty")
        return {"flagged": 0}

    # Bulk update
    await db.execute(
        update(Claim)
        .where(Claim.expires_at <= now)
        .where(Claim.is_stale.is_(False))
        .values(is_stale=True)
    )
    await db.flush()

    logger.info("retention.sweep_complete", claims_flagged=count)
    return {"flagged": count}


async def start_retention_worker() -> None:
    """
    Long-running asyncio task: sweeps for expired claims on the same
    interval as the re-verification worker.
    """
    interval = settings.reverify_sweep_interval_seconds
    logger.info("retention.worker_started", interval_seconds=interval)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    await _retention_sweep_once(db)
        except Exception as exc:
            logger.error("retention.worker_error", error=str(exc))

        await asyncio.sleep(interval)
