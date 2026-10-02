"""
Suppression API routes  —  /api/v1/suppressions

Implements the V1.5 hard opt-out (suppression list):
  POST   /api/v1/suppressions        — Add a suppression (data subject or admin)
  GET    /api/v1/suppressions        — List all suppressions (admin)
  DELETE /api/v1/suppressions/{id}   — Remove a suppression entry (admin)

A suppressed identity is:
  1. Blocked from being written to the database in future search runs.
  2. Excluded from all search results and profile reads.

The match_key is SHA-256(lowercase(name)), so the raw name is never stored.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.policy import get_current_user
from app.database import get_db
from app.models.governance import Dispute, DisputeStatus, Suppression
from app.models.person import Person, PersonStatus

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class SuppressionRequest(BaseModel):
    """Request body for adding a suppression."""
    name: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Full name of the person to suppress. The raw name is NOT stored — only a SHA-256 hash.",
        examples=["Jane Doe"],
    )
    reason: str | None = Field(
        None,
        max_length=1024,
        description="Optional reason for the suppression (e.g. 'data subject removal request', dispute ID).",
    )
    dispute_id: uuid.UUID | None = Field(
        None,
        description="If this suppression is a result of resolving a dispute, link the dispute ID here.",
    )


class SuppressionOut(BaseModel):
    """Suppression entry returned by the API."""
    id: uuid.UUID
    match_key: str = Field(..., description="SHA-256 hash of the suppressed name (raw name not stored).")
    reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SuppressionListResponse(BaseModel):
    items: list[SuppressionOut]
    total: int
    page: int
    page_size: int


class SuppressionResponse(BaseModel):
    suppression_id: uuid.UUID
    match_key: str
    message: str
    created_at: datetime


# ── Helpers ────────────────────────────────────────────────────────────────────

def _suppression_key(name: str) -> str:
    """SHA-256 of the canonical (lowercased, stripped) name."""
    return hashlib.sha256(name.strip().lower().encode()).hexdigest()


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=SuppressionResponse,
    status_code=201,
    summary="Add a hard opt-out suppression",
    description=(
        "Adds an identity to the suppression list. Once suppressed, this identity "
        "will not be re-ingested, will not appear in search results, and any future "
        "collection pipeline run will skip it at the source collection step. "
        "The raw name is never stored — only a SHA-256 hash is persisted."
    ),
)
async def add_suppression(
    body: SuppressionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user),
) -> SuppressionResponse:
    key = _suppression_key(body.name)

    # Idempotent — if already suppressed, return the existing entry
    existing = await db.execute(
        select(Suppression).where(Suppression.match_key == key).limit(1)
    )
    existing_row = existing.scalar_one_or_none()
    if existing_row is not None:
        logger.info("suppression.already_exists", match_key=key[:12])
        return SuppressionResponse(
            suppression_id=existing_row.id,
            match_key=key,
            message="This identity is already on the suppression list.",
            created_at=existing_row.created_at,
        )

    suppression = Suppression(match_key=key)
    db.add(suppression)

    # ── Mark matching Person rows as suppressed ───────────────────────────────
    # This ensures existing profiles are hidden from search results immediately,
    # even before the next collection run would skip them.
    persons_res = await db.execute(
        select(Person).where(Person.canonical_name == body.name.strip())
    )
    suppressed_count = 0
    for person in persons_res.scalars().all():
        person.status = PersonStatus.suppressed
        suppressed_count += 1

    # ── Link to dispute if provided ───────────────────────────────────────────
    if body.dispute_id:
        dispute_res = await db.execute(
            select(Dispute).where(Dispute.id == body.dispute_id).limit(1)
        )
        dispute = dispute_res.scalar_one_or_none()
        if dispute:
            dispute.status = DisputeStatus.resolved
            dispute.resolved_at = datetime.now(timezone.utc)

    await db.flush()

    logger.info(
        "suppression.created",
        suppression_id=str(suppression.id),
        match_key=key[:12],
        persons_suppressed=suppressed_count,
        linked_dispute=str(body.dispute_id) if body.dispute_id else None,
        actor=user_id,
    )

    return SuppressionResponse(
        suppression_id=suppression.id,
        match_key=key,
        message=(
            "Identity suppressed. It will be excluded from all future ingestion and search results. "
            f"{suppressed_count} existing profile(s) have been marked suppressed."
        ),
        created_at=suppression.created_at,
    )


@router.get(
    "/",
    response_model=SuppressionListResponse,
    summary="List all suppression entries (admin)",
    description="Returns a paginated list of all suppression entries. Raw names are not stored.",
)
async def list_suppressions(
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 50,
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user),
) -> SuppressionListResponse:
    offset = (page - 1) * page_size

    total_res = await db.execute(select(func.count()).select_from(Suppression))
    total = total_res.scalar_one()

    rows_res = await db.execute(
        select(Suppression)
        .order_by(Suppression.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = rows_res.scalars().all()

    return SuppressionListResponse(
        items=[
            SuppressionOut(
                id=row.id,
                match_key=row.match_key,
                reason=None,   # reason field not on ORM yet; placeholder
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete(
    "/{suppression_id}",
    status_code=204,
    summary="Remove a suppression entry (admin)",
    description=(
        "Removes a suppression entry. Use with caution — this re-enables "
        "future ingestion and search visibility for the suppressed identity."
    ),
)
async def remove_suppression(
    suppression_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user),
) -> None:
    result = await db.execute(
        select(Suppression).where(Suppression.id == suppression_id).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Suppression {suppression_id} not found.",
        )

    await db.delete(row)
    await db.flush()

    logger.info(
        "suppression.removed",
        suppression_id=str(suppression_id),
        match_key=row.match_key[:12],
        actor=user_id,
    )
