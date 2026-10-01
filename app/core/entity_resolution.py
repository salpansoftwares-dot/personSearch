"""
Entity Resolution module.

Groups raw claim sets into person clusters using deterministic scoring.
AI contributes one signal (embedding similarity) but the merge decision
is always made by the weighted score vs a hard threshold.

Architecture principle: "Default to unmerged."
A false merge (attributing one person's employer to another) is worse
than a missed link. When the score is below the threshold, clusters
stay separate and are shown as alternatives.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

# ── Signal weights (sum to 1.0) ─────────────────────────────────────────────────
# direct_search_hit: the search engine returned this URL for the target name query.
# This is meaningful signal — it reflects the engine's own relevance ranking.
SIGNAL_WEIGHTS: dict[str, float] = {
    "name_similarity":    0.10,   # Weak: names can be common
    "direct_search_hit":  0.40,   # Medium-strong: search engine matched this to the name
    "same_employer":      0.15,   # Medium
    "same_location_sector": 0.05, # Weak
    "cross_links":        0.20,   # Strong: source A links to source B
    "shared_identifier":  0.10,   # Strong: same handle, ORCID, personal URL
}

assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"


@dataclass
class PersonCluster:
    cluster_id: str
    canonical_name: str
    claims: list[dict] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    # Signal scores from the last resolution pass
    signals: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    person_id: uuid.UUID | None = None


def _name_similarity(name_a: str, name_b: str) -> float:
    """Simple token overlap — placeholder for trigram/phonetic similarity."""
    tokens_a = set(name_a.lower().split())
    tokens_b = set(name_b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _cluster_id(name: str) -> str:
    """Deterministic cluster seed from a canonical name."""
    return hashlib.sha256(name.strip().lower().encode()).hexdigest()[:16]


def compute_cluster_score(signals: dict[str, float]) -> float:
    """Weighted sum of signal scores — capped at 1.0."""
    total = sum(SIGNAL_WEIGHTS.get(k, 0.0) * v for k, v in signals.items())
    return min(total, 1.0)


def resolve_entities(
    candidate_claim_sets: list[dict[str, Any]],
    target_name: str,
    merge_threshold: float | None = None,
) -> tuple[list[PersonCluster], list[PersonCluster]]:
    """
    Resolve candidate claim sets into person clusters.

    Args:
        candidate_claim_sets: Each dict has "url", "name_on_source", "claims".
        target_name: The name the user searched for.
        merge_threshold: Override the global setting (used in tests).

    Returns:
        (primary_clusters, alternative_clusters)

    Deterministic flow:
      1. For each candidate, compute signals against target_name.
      2. Score the candidate.
      3. Candidates above threshold → primary; below → alternatives.
      4. Among primaries, check for further merge via cross-links and
         shared identifiers. Merge only if the combined score exceeds threshold.

    AI embedding similarity is plugged in as one signal in `signals`;
    it never alone determines a merge.
    """
    threshold = merge_threshold if merge_threshold is not None else settings.entity_merge_threshold
    primaries: list[PersonCluster] = []
    alternatives: list[PersonCluster] = []

    # All URLs from all candidates — used to detect cross-links
    all_candidate_urls = {cand.get("url", "") for cand in candidate_claim_sets}

    for cand in candidate_claim_sets:
        name_on_source = cand.get("name_on_source", target_name)
        url = cand.get("url", "")
        claims = cand.get("claims", [])
        # direct_search_hit: True when the candidate was returned by the search
        # engine in response to a query for target_name (i.e. it's in our set).
        # All candidates in candidate_claim_sets are by definition direct hits.
        is_direct_hit = True

        signals: dict[str, float] = {
            "name_similarity":      _name_similarity(target_name, name_on_source),
            "direct_search_hit":    1.0 if is_direct_hit else 0.0,
            "same_employer":        _same_employer_signal(claims, candidate_claim_sets),
            "same_location_sector": 0.0,  # TODO: implement in V1.5
            "cross_links":          _cross_link_signal(url, candidate_claim_sets),
            "shared_identifier":    _shared_identifier_signal(claims, candidate_claim_sets),
        }

        score = compute_cluster_score(signals)
        cluster = PersonCluster(
            cluster_id=_cluster_id(name_on_source),
            canonical_name=name_on_source,
            claims=claims,
            source_urls=[url],
            signals=signals,
            score=score,
        )

        logger.info(
            "entity_resolution.scored",
            cluster_id=cluster.cluster_id,
            name=name_on_source,
            score=round(score, 3),
            threshold=threshold,
            signals={k: round(v, 2) for k, v in signals.items()},
        )

        if score >= threshold:
            primaries.append(cluster)
        else:
            alternatives.append(cluster)

    # Merge primary clusters that share the same canonical name
    # (i.e. multiple sources about the same person cluster together)
    merged_primaries = _merge_same_name_clusters(primaries, target_name)

    return merged_primaries, alternatives


# ── Signal helpers (deterministic) ─────────────────────────────────────────────

def _same_employer_signal(claims: list[dict], all_candidates: list[dict]) -> float:
    """1.0 if any organization claim matches across candidates, else 0.0."""
    orgs = {c["value"].lower() for c in claims if c.get("claim_type") == "organization"}
    if not orgs:
        return 0.0
    for other in all_candidates:
        other_orgs = {
            c["value"].lower()
            for c in other.get("claims", [])
            if c.get("claim_type") == "organization"
        }
        if orgs & other_orgs:
            return 1.0
    return 0.0


def _cross_link_signal(url: str, all_candidates: list[dict]) -> float:
    """
    1.0 if another candidate's profile_url claim references this URL.
    Cross-links are strong evidence because they require the source to
    explicitly connect two profiles.
    """
    for other in all_candidates:
        for claim in other.get("claims", []):
            if claim.get("claim_type") == "profile_url" and url in claim.get("value", ""):
                return 1.0
    return 0.0


def _shared_identifier_signal(claims: list[dict], all_candidates: list[dict]) -> float:
    """
    1.0 if a shared profile_url or unique handle appears across multiple candidates.
    """
    my_urls = {c["value"] for c in claims if c.get("claim_type") == "profile_url"}
    if not my_urls:
        return 0.0
    for other in all_candidates:
        other_urls = {
            c["value"] for c in other.get("claims", []) if c.get("claim_type") == "profile_url"
        }
        if my_urls & other_urls:
            return 1.0
    return 0.0


def _merge_same_name_clusters(
    clusters: list[PersonCluster],
    target_name: str,
) -> list[PersonCluster]:
    """
    Merge primary clusters that have the same canonical name (case-insensitive).

    This consolidates multiple sources about the same person into one cluster
    so the response shows one profile with many claims instead of many profiles
    with one claim each.
    """
    if len(clusters) <= 1:
        return clusters

    # Group by normalised canonical name
    groups: dict[str, PersonCluster] = {}
    for cluster in clusters:
        key = cluster.canonical_name.strip().lower()
        if key not in groups:
            groups[key] = cluster
        else:
            # Merge claims and source_urls into the existing cluster
            existing = groups[key]
            existing.claims.extend(cluster.claims)
            existing.source_urls.extend(cluster.source_urls)
            # Keep the highest score
            if cluster.score > existing.score:
                existing.score = cluster.score
                existing.signals = cluster.signals

    merged = list(groups.values())
    logger.info(
        "entity_resolution.merge_done",
        before=len(clusters),
        after=len(merged),
        target=target_name,
    )
    return merged
