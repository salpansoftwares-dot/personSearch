"""
Conflict and Staleness Detection Engine.

Architecture principle (Section 7):
"Stage: Conflict and staleness
What the model/system does: Flags disagreements between sources and whether they
look like a job change or a different person.
Guardrail: Flags prompt review or lower confidence; they never overwrite a claim."
"""

import uuid
from datetime import datetime, timezone
import structlog

from app.config import settings
from app.core.entity_resolution import _PROFESSION_BUCKETS, _normalize_org
from app.schemas.search import ClaimOut, ConflictFlag, StalenessFlag

logger = structlog.get_logger(__name__)

_TRANSITION_KEYWORDS = {
    "former", "previously", "previous", "ex-", "past", "until", "prior", "alumnus", "alumna", "left", "earlier"
}


def _detect_organization_conflicts(claims: list[ClaimOut]) -> list[ConflictFlag]:
    """
    Detect conflicting employers and determine if they represent a career transition
    or concurrent source disagreement.
    """
    flags: list[ConflictFlag] = []
    org_claims: list[ClaimOut] = [c for c in claims if c.type == "organization" and c.value]

    if len(org_claims) < 2:
        return flags

    # Group by normalized organization
    seen_orgs: dict[str, list[ClaimOut]] = {}
    for c in org_claims:
        norm = _normalize_org(c.value)
        if norm:
            seen_orgs.setdefault(norm, []).append(c)

    distinct_orgs = list(seen_orgs.keys())
    if len(distinct_orgs) < 2:
        return flags

    # Check pairs of distinct organizations
    for i in range(len(distinct_orgs)):
        for j in range(i + 1, len(distinct_orgs)):
            org1 = distinct_orgs[i]
            org2 = distinct_orgs[j]
            claims1 = seen_orgs[org1]
            claims2 = seen_orgs[org2]

            # Check if any evidence contains transition keywords
            has_transition = False
            for c in claims1 + claims2:
                for ev in c.evidence:
                    exc = ev.excerpt.lower()
                    if any(kw in exc for kw in _TRANSITION_KEYWORDS):
                        has_transition = True
                        break

            # Check timestamp dates if available
            dates1 = [ev.retrieved_at for c in claims1 for ev in c.evidence if ev.retrieved_at]
            dates2 = [ev.retrieved_at for c in claims2 for ev in c.evidence if ev.retrieved_at]

            time_delta_days = 0
            if dates1 and dates2:
                max1 = max(dates1)
                max2 = max(dates2)
                time_delta_days = abs((max1 - max2).days)
                if time_delta_days > 180:
                    has_transition = True

            combined_claim_ids = [c.claim_id for c in claims1 + claims2]

            if has_transition:
                flags.append(
                    ConflictFlag(
                        conflict_id=f"conf-jobchange-{uuid.uuid4().hex[:8]}",
                        conflict_type="job_change",
                        severity="low",
                        claim_ids=combined_claim_ids,
                        description=(
                            f"Likely career transition between '{claims1[0].value}' and '{claims2[0].value}'. "
                            f"One or more sources reflect previous affiliation."
                        ),
                        action_prompt="Confirm latest primary organization.",
                    )
                )
            else:
                flags.append(
                    ConflictFlag(
                        conflict_id=f"conf-disagree-{uuid.uuid4().hex[:8]}",
                        conflict_type="source_disagreement",
                        severity="medium",
                        claim_ids=combined_claim_ids,
                        description=(
                            f"Sources report different primary organizations ('{claims1[0].value}' vs '{claims2[0].value}') "
                            f"without transition markers."
                        ),
                        action_prompt="Review recommended: check for dual affiliations or recent position changes.",
                    )
                )

    return flags


def _detect_occupation_conflicts(claims: list[ClaimOut]) -> list[ConflictFlag]:
    """
    Detect conflicting occupations from completely disparate sectors.
    """
    flags: list[ConflictFlag] = []
    occ_claims: list[ClaimOut] = [c for c in claims if c.type in ("occupation", "role") and c.value]

    if len(occ_claims) < 2:
        return flags

    # Map each claim to its professional bucket
    claim_buckets: list[tuple[ClaimOut, set[str]]] = []
    for c in occ_claims:
        val_lower = c.value.lower()
        buckets = {
            b for b, kw_set in _PROFESSION_BUCKETS.items()
            if any(kw in val_lower for kw in kw_set)
        }
        if buckets:
            claim_buckets.append((c, buckets))

    # Compare pairs
    for i in range(len(claim_buckets)):
        for j in range(i + 1, len(claim_buckets)):
            c1, b1 = claim_buckets[i]
            c2, b2 = claim_buckets[j]
            if not (b1 & b2):
                # Disjoint sectors!
                flags.append(
                    ConflictFlag(
                        conflict_id=f"conf-occ-{uuid.uuid4().hex[:8]}",
                        conflict_type="possible_different_person",
                        severity="high",
                        claim_ids=[c1.claim_id, c2.claim_id],
                        description=(
                            f"Disparate profession sectors detected: '{c1.value}' ({', '.join(b1)}) "
                            f"vs '{c2.value}' ({', '.join(b2)})."
                        ),
                        action_prompt="High-priority review: ensure claims are not conflating two individuals with the same name.",
                    )
                )

    return flags


def _detect_staleness(
    claims: list[ClaimOut],
    now: datetime | None = None,
) -> tuple[list[ClaimOut], list[StalenessFlag]]:
    """
    Identify stale claims based on expiry window and database staleness flags.
    Calibrates confidence without ever deleting or overwriting claims.
    """
    current_time = now or datetime.now(timezone.utc)
    staleness_flags: list[StalenessFlag] = []
    updated_claims: list[ClaimOut] = []

    expiry_days = settings.claim_expiry_days

    for c in claims:
        is_stale = getattr(c, "is_stale", False)
        staleness_reason = getattr(c, "staleness_reason", None)
        days_old = None
        source_url = c.evidence[0].source_url if c.evidence else ""

        # Compute age from evidence retrieved_at
        if c.evidence and c.evidence[0].retrieved_at:
            retrieved_at = c.evidence[0].retrieved_at
            if retrieved_at.tzinfo is None:
                retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
            delta = current_time - retrieved_at
            days_old = max(delta.days, 0)
            if days_old > expiry_days:
                is_stale = True
                staleness_reason = f"Claim is {days_old} days old (exceeds {expiry_days}-day freshness SLA)."

        if is_stale:
            reason = staleness_reason or "Source has been flagged as stale or unreachable."
            staleness_flags.append(
                StalenessFlag(
                    claim_id=c.claim_id,
                    source_url=source_url,
                    days_old=days_old,
                    reason=reason,
                )
            )
            # Calibrate confidence down slightly for stale claims (never 0, never overwrite)
            adjusted_conf = min(round(c.confidence * 0.85, 2), 0.70)
            c_copy = c.model_copy(
                update={
                    "is_stale": True,
                    "staleness_reason": reason,
                    "confidence": adjusted_conf,
                }
            )
            updated_claims.append(c_copy)
        else:
            updated_claims.append(c)

    return updated_claims, staleness_flags


def detect_conflicts_and_staleness(
    claims: list[ClaimOut],
    now: datetime | None = None,
) -> tuple[list[ClaimOut], list[ConflictFlag], list[StalenessFlag]]:
    """
    Inspect a set of claims for a person profile.
    Returns:
      (calibrated_claims, conflict_flags, staleness_flags)
    """
    if not claims:
        return [], [], []

    # 1. Detect staleness and calibrate confidence
    calibrated_claims, staleness_flags = _detect_staleness(claims, now=now)

    # 2. Detect organization conflicts (job changes vs concurrent disagreements)
    org_conflicts = _detect_organization_conflicts(calibrated_claims)

    # 3. Detect occupation / sector conflicts
    occ_conflicts = _detect_occupation_conflicts(calibrated_claims)

    all_conflicts = org_conflicts + occ_conflicts

    logger.info(
        "conflict_detector.done",
        total_claims=len(claims),
        conflicts=len(all_conflicts),
        staleness_flags=len(staleness_flags),
    )

    return calibrated_claims, all_conflicts, staleness_flags
