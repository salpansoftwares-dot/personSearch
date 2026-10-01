"""
Disputes API routes  —  POST /api/v1/disputes
"""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.policy import get_current_user
from app.database import get_db
from app.models.claim import Claim
from app.models.governance import Dispute
from app.models.person import Person
from app.schemas.person import DisputeRequest, DisputeResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "/",
    response_model=DisputeResponse,
    status_code=201,
    summary="Submit a correction or removal request",
    description=(
        "Data subjects or their representatives can request correction "
        "or removal of a profile or specific claim. "
        "Requests are acknowledged and resolved within the configured SLA."
    ),
)
async def submit_dispute(
    body: DisputeRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user),
) -> DisputeResponse:
    if not body.person_id and not body.claim_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either person_id or claim_id must be provided to file a dispute.",
        )

    if body.person_id is not None:
        p_res = await db.execute(select(Person).where(Person.id == body.person_id))
        if p_res.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Person {body.person_id} not found.",
            )

    if body.claim_id is not None:
        c_res = await db.execute(select(Claim).where(Claim.id == body.claim_id))
        if c_res.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Claim {body.claim_id} not found.",
            )

    dispute = Dispute(
        person_id=body.person_id,
        claim_id=body.claim_id,
        submitter=body.submitter,
        reason=body.reason,
    )
    db.add(dispute)
    await db.flush()

    logger.info(
        "dispute.submitted",
        dispute_id=str(dispute.id),
        person_id=str(body.person_id),
        claim_id=str(body.claim_id),
        submitter=body.submitter,
    )

    return DisputeResponse(
        dispute_id=dispute.id,
        status=dispute.status.value,
        message=(
            "Your request has been received and will be reviewed within the defined SLA. "
            "You will be contacted at the submitter reference you provided."
        ),
        created_at=datetime.now(timezone.utc),
    )
