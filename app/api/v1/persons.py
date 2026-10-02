"""
Persons API routes  —  GET /api/v1/persons/{person_id}
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.policy import get_current_user
from app.database import get_db
from app.models.claim import Claim
from app.models.person import Person, PersonClaim, PersonStatus
from app.models.source import Source
from app.core.summarizer import generate_profile_summary
from app.core.conflict_detector import detect_conflicts_and_staleness
from app.core.report_generator import build_evidence_report, export_report_csv, export_report_html
from app.schemas.person import PersonProfile
from app.schemas.report import EvidenceReport
from app.schemas.search import ClaimOut, EvidenceItem, ProfileSummary

logger = structlog.get_logger(__name__)
router = APIRouter()



@router.get(
    "/{person_id}",
    response_model=PersonProfile,
    summary="Retrieve a person profile with full evidence",
    description=(
        "Returns all verified claims for a person cluster, each with its "
        "source, evidence excerpt and retrieval date."
    ),
)
async def get_person(
    person_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user),
) -> PersonProfile:
    """
    Fetch a person profile and all linked claims + source evidence.
    """
    # 1. Fetch Person record
    person_res = await db.execute(
        select(Person).where(Person.id == person_id)
    )
    person = person_res.scalar_one_or_none()
    if person is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Person {person_id} not found.",
        )

    if person.status == PersonStatus.suppressed:
        logger.warning("persons.get.suppressed", person_id=str(person_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Person {person_id} not found.",
        )

    # 2. Fetch linked claims with joined source
    pc_stmt = (
        select(PersonClaim)
        .options(
            joinedload(PersonClaim.claim).joinedload(Claim.source)
        )
        .where(PersonClaim.person_id == person_id)
    )
    pc_res = await db.execute(pc_stmt)
    person_claims = pc_res.scalars().all()

    claims_out: list[ClaimOut] = []
    for pc in person_claims:
        claim = pc.claim
        if not claim:
            continue
        source = claim.source

        evidence = [
            EvidenceItem(
                source_url=source.url if source else "",
                source_type=source.source_type if source else "unknown",
                excerpt=claim.evidence_span,
                retrieved_at=source.retrieved_at if source else claim.extracted_at,
            )
        ]

        claims_out.append(
            ClaimOut(
                claim_id=claim.id,
                type=claim.claim_type if isinstance(claim.claim_type, str) else claim.claim_type.value,
                value=claim.value,
                confidence=pc.link_confidence or claim.confidence,
                evidence=evidence,
                is_stale=claim.is_stale,
            )
        )

    # 3. Detect conflicts and staleness
    calibrated_claims, conflict_flags, staleness_flags = detect_conflicts_and_staleness(claims_out)

    # 4. Find alternatives (other active profiles with same or similar name)
    alt_stmt = (
        select(Person.id)
        .where(Person.canonical_name == person.canonical_name)
        .where(Person.id != person_id)
        .where(Person.status == PersonStatus.active)
        .limit(10)
    )
    alt_res = await db.execute(alt_stmt)
    alternatives = [row[0] for row in alt_res.fetchall()]

    logger.info(
        "persons.get.success",
        person_id=str(person_id),
        claims_count=len(calibrated_claims),
        conflicts_count=len(conflict_flags),
        staleness_count=len(staleness_flags),
        alternatives_count=len(alternatives),
    )

    # 5. Resolve summary (from stored json or on-the-fly synthesis)
    summary: ProfileSummary | None = None
    if person.summary_json:
        try:
            summary = ProfileSummary.model_validate(person.summary_json)
        except Exception:
            summary = None

    if summary is None and calibrated_claims:
        summary = await generate_profile_summary(person.canonical_name, calibrated_claims)

    return PersonProfile(
        person_id=person.id,
        canonical_name=person.canonical_name,
        status=person.status.value if hasattr(person.status, "value") else str(person.status),
        updated_at=person.updated_at,
        claims=calibrated_claims,
        summary=summary if (summary and summary.sentences) else None,
        conflict_flags=conflict_flags,
        staleness_flags=staleness_flags,
        alternatives=alternatives,
    )


@router.get(
    "/{person_id}/report",
    summary="Export due-diligence evidence report",
    description="Export a person profile and full claim provenance as JSON, CSV, or printable HTML.",
    response_model=EvidenceReport,
)
async def get_person_report(
    person_id: uuid.UUID,
    format: str = Query("json", pattern="^(json|csv|html)$"),
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user),
):

    profile = await get_person(person_id=person_id, db=db, user_id=user_id)
    report = build_evidence_report(profile)

    if format == "csv":
        csv_content = export_report_csv(report)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="evidence_report_{person_id}.csv"'},
        )
    elif format == "html":
        html_content = export_report_html(report)
        return Response(
            content=html_content,
            media_type="text/html",
            headers={"Content-Disposition": f'inline; filename="evidence_report_{person_id}.html"'},
        )

    return report

