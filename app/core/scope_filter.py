"""
Scope Filter — claim-type allowlist.

This is the hard gate between extraction and storage.
Any claim whose type is not in the ClaimType enum is silently dropped.
Out-of-scope data (home address, personal email, etc.) never reaches
the database — this is enforced in code, not policy alone.
"""

import structlog

from app.models.claim import ClaimType

logger = structlog.get_logger(__name__)

# The complete allowlist, derived directly from the ClaimType enum.
_ALLOWED_TYPES: frozenset[str] = frozenset(ct.value for ct in ClaimType)


def is_allowed(claim_type: str) -> bool:
    return claim_type in _ALLOWED_TYPES


def filter_claims(raw_claims: list[dict]) -> list[dict]:
    """
    Return only claims whose type is on the allowlist.

    Args:
        raw_claims: list of dicts, each must have a "claim_type" key.

    Returns:
        Filtered list. Dropped claims are logged.
    """
    allowed, dropped = [], []
    for claim in raw_claims:
        ctype = claim.get("claim_type", "")
        if is_allowed(ctype):
            allowed.append(claim)
        else:
            dropped.append(ctype)

    if dropped:
        logger.warning(
            "scope_filter.dropped",
            dropped_types=dropped,
            count=len(dropped),
        )

    logger.info(
        "scope_filter.result",
        allowed=len(allowed),
        dropped=len(dropped),
    )
    return allowed
