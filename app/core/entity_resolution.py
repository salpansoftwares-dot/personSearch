"""
Entity Resolution module.

Groups raw candidate claim sets into distinct person clusters using deterministic
evidence scoring and conservative pairwise merge rules.

Architecture principle: "Default to unmerged."
A false merge (attributing one person's employer, role, or links to another individual)
is worse than a missed link. Sources from different employers, conflicting professions,
or without corroborating cross-links/shared identifiers stay separate and are presented
as alternative possible matches.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class PersonCluster:
    cluster_id: str
    canonical_name: str
    claims: list[dict] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    person_id: uuid.UUID | None = None


# ── Text normalization & similarity ──────────────────────────────────────────

def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _name_similarity(name_a: str, name_b: str) -> float:
    """Token overlap (Jaccard similarity) between two names."""
    tokens_a = set(_normalize_name(name_a).split())
    tokens_b = set(_normalize_name(name_b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _normalize_org(org: str) -> str:
    """Normalize organization names for reliable corroboration."""
    org = org.lower().strip()
    org = re.sub(r"[^\w\s]", "", org)
    org = re.sub(
        r"\b(plc|ltd|limited|inc|incorporated|corp|corporation|llc|co|company|group)\b",
        "",
        org,
    )
    return re.sub(r"\s+", " ", org).strip()


def _extract_orgs(claims: list[dict]) -> set[str]:
    orgs = set()
    for c in claims:
        if c.get("claim_type") == "organization" and c.get("value"):
            norm = _normalize_org(c["value"])
            if len(norm) >= 2:
                orgs.add(norm)
    return orgs


def _extract_identifiers(claims: list[dict], source_urls: list[str]) -> set[str]:
    """
    Extract unique platform handles or canonical URLs from profile_url claims and source_urls.
    E.g. 'github.com/alice', 'linkedin.com/in/alice', 'orcid.org/0000-...'
    """
    identifiers = set()
    urls = list(source_urls) + [
        c["value"] for c in claims if c.get("claim_type") == "profile_url" and c.get("value")
    ]
    for raw in urls:
        u = raw.strip().lower()
        if not u:
            continue
        try:
            parsed = urlparse(u if "://" in u else f"https://{u}")
            netloc = parsed.netloc.replace("www.", "")
            path = parsed.path.rstrip("/")
            if netloc and path and len(path) > 1:
                identifiers.add(f"{netloc}{path}")
        except Exception:
            identifiers.add(u)
    return identifiers


def _extract_occupations(claims: list[dict]) -> set[str]:
    occ = set()
    for c in claims:
        if c.get("claim_type") in ("occupation", "role") and c.get("value"):
            val = re.sub(r"[^\w\s]", "", c["value"].lower()).strip()
            if val:
                occ.add(val)
    return occ


def _cluster_id(name: str, source_urls: list[str], claims: list[dict]) -> str:
    """Deterministic cluster seed incorporating name, sources, and organizations."""
    orgs = sorted(_extract_orgs(claims))
    key = f"{_normalize_name(name)}|{sorted(source_urls)}|{orgs}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ── Pairwise signals between two clusters ────────────────────────────────────

_PROFESSION_BUCKETS = {
    "medical": {"doctor", "physician", "surgeon", "nurse", "pediatrician", "dentist", "pharmacist", "clinical"},
    "tech": {"software", "developer", "engineer", "programmer", "devops", "architect", "data scientist", "web"},
    "legal": {"lawyer", "advocate", "attorney", "barrister", "solicitor", "judge", "magistrate"},
    "finance": {"accountant", "auditor", "banker", "actuary", "tax"},
}


def _has_cross_link(c1: PersonCluster, c2: PersonCluster) -> bool:
    """True if c1 references c2's URLs or c2 references c1's URLs."""
    urls1 = {u.lower().rstrip("/") for u in c1.source_urls if u}
    urls2 = {u.lower().rstrip("/") for u in c2.source_urls if u}

    for c in c1.claims:
        val = (c.get("value") or "").lower().rstrip("/")
        span = (c.get("evidence_span") or "").lower()
        for u in urls2:
            if u and (u in val or u in span):
                return True

    for c in c2.claims:
        val = (c.get("value") or "").lower().rstrip("/")
        span = (c.get("evidence_span") or "").lower()
        for u in urls1:
            if u and (u in val or u in span):
                return True

    return False


def _has_shared_identifier(c1: PersonCluster, c2: PersonCluster) -> bool:
    """True if c1 and c2 share a specific profile URL or platform handle."""
    id1 = _extract_identifiers(c1.claims, c1.source_urls)
    id2 = _extract_identifiers(c2.claims, c2.source_urls)
    valid1 = {i for i in id1 if "/" in i and not i.endswith(".com") and not i.endswith(".org")}
    valid2 = {i for i in id2 if "/" in i and not i.endswith(".com") and not i.endswith(".org")}
    return bool(valid1 & valid2)


def _compare_employers(c1: PersonCluster, c2: PersonCluster) -> tuple[bool, bool]:
    """
    Returns (same_employer, has_employer_conflict).
    - same_employer is True if normalized organizations overlap.
    - has_employer_conflict is True if both have organizations, but ZERO overlap.
    """
    orgs1 = _extract_orgs(c1.claims)
    orgs2 = _extract_orgs(c2.claims)

    if not orgs1 or not orgs2:
        return False, False

    if orgs1 & orgs2:
        return True, False

    for o1 in orgs1:
        for o2 in orgs2:
            if o1 in o2 or o2 in o1:
                return True, False

    return False, True


def _compare_occupations(c1: PersonCluster, c2: PersonCluster) -> tuple[bool, bool]:
    occ1 = _extract_occupations(c1.claims)
    occ2 = _extract_occupations(c2.claims)
    if not occ1 or not occ2:
        return False, False

    tokens1 = set(" ".join(occ1).split())
    tokens2 = set(" ".join(occ2).split())
    if tokens1 & tokens2:
        return True, False

    b1 = {b for b, keywords in _PROFESSION_BUCKETS.items() if any(k in " ".join(occ1) for k in keywords)}
    b2 = {b for b, keywords in _PROFESSION_BUCKETS.items() if any(k in " ".join(occ2) for k in keywords)}

    if b1 and b2 and not (b1 & b2):
        return False, True

    return False, False


def evaluate_pairwise_merge(
    c1: PersonCluster,
    c2: PersonCluster,
) -> tuple[bool, float, dict[str, float]]:
    """
    Evaluate whether two clusters should be merged into a single person profile.

    Rules:
      1. Default to unmerged.
      2. If employers conflict and there are no cross-links / shared IDs, VETO merge.
      3. If occupations conflict and there are no corroborating links/IDs, VETO merge.
      4. A matching name alone is NEVER sufficient to merge.
    """
    name_sim = _name_similarity(c1.canonical_name, c2.canonical_name)
    if name_sim < 0.5:
        return False, 0.0, {"name_similarity": name_sim}

    cross_link = _has_cross_link(c1, c2)
    shared_id = _has_shared_identifier(c1, c2)
    same_emp, emp_conflict = _compare_employers(c1, c2)
    same_occ, occ_conflict = _compare_occupations(c1, c2)

    signals: dict[str, float] = {
        "name_similarity": round(name_sim, 2),
        "cross_links": 1.0 if cross_link else 0.0,
        "shared_identifier": 1.0 if shared_id else 0.0,
        "same_employer": 1.0 if same_emp else 0.0,
    }

    # Hard conflict vetoes:
    if emp_conflict and not (cross_link or shared_id):
        signals["employer_conflict"] = 1.0
        return False, 0.0, signals

    if occ_conflict and not (cross_link or shared_id or same_emp):
        signals["occupation_conflict"] = 1.0
        return False, 0.0, signals

    # Corroboration required: A matching name alone is never enough
    has_corroboration = cross_link or shared_id or same_emp
    if not has_corroboration:
        return False, round(0.10 * name_sim, 2), signals

    score = (
        (0.35 if cross_link else 0.0) +
        (0.35 if shared_id else 0.0) +
        (0.20 if same_emp else 0.0) +
        (0.10 * name_sim)
    )

    can_merge = score >= 0.30
    return can_merge, min(round(score, 3), 1.0), signals


# ── Top-level resolution ──────────────────────────────────────────────────────

def resolve_entities(
    candidate_claim_sets: list[dict[str, Any]],
    target_name: str,
    hints: Any | None = None,
    merge_threshold: float | None = None,
) -> tuple[list[PersonCluster], list[PersonCluster]]:
    """
    Resolve candidate claim sets into distinct person clusters.

    Args:
        candidate_claim_sets: List of dicts, each with "url", "name_on_source", "claims".
        target_name: The name the user searched for.
        hints: Optional search hints (SearchHints model or dict).
        merge_threshold: Override the global setting.

    Returns:
        (primary_clusters, alternative_clusters)
    """
    threshold = merge_threshold if merge_threshold is not None else settings.entity_merge_threshold

    # 1. Initialize individual clusters for each candidate
    clusters: list[PersonCluster] = []
    for cand in candidate_claim_sets:
        name_on_source = cand.get("name_on_source") or target_name
        url = cand.get("url", "")
        claims = cand.get("claims", [])
        if not claims:
            continue

        urls = [url] if url else []
        cluster = PersonCluster(
            cluster_id=_cluster_id(name_on_source, urls, claims),
            canonical_name=name_on_source,
            claims=claims,
            source_urls=urls,
            signals={},
            score=0.0,
        )
        clusters.append(cluster)

    logger.info("entity_resolution.initial_candidates", count=len(clusters))

    # 2. Pairwise agglomerative merging: merge only corroborated clusters
    merged = True
    while merged and len(clusters) > 1:
        merged = False
        best_pair = None
        best_score = 0.0

        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                can_merge, pair_score, pair_signals = evaluate_pairwise_merge(clusters[i], clusters[j])
                if can_merge and pair_score > best_score:
                    best_score = pair_score
                    best_pair = (i, j, pair_signals)

        if best_pair is not None and best_score >= 0.30:
            i, j, pair_signals = best_pair
            c1, c2 = clusters[i], clusters[j]

            # Merge claims from c2 into c1 (avoid exact duplicates)
            seen_claims = {
                (c.get("claim_type"), (c.get("value") or "").lower().strip())
                for c in c1.claims
            }
            for c in c2.claims:
                key = (c.get("claim_type"), (c.get("value") or "").lower().strip())
                if key not in seen_claims:
                    seen_claims.add(key)
                    c1.claims.append(c)

            # Merge source URLs
            for u in c2.source_urls:
                if u not in c1.source_urls:
                    c1.source_urls.append(u)

            # Name preference: keep longer or more specific name
            if len(c2.canonical_name) > len(c1.canonical_name):
                c1.canonical_name = c2.canonical_name

            c1.signals.update(pair_signals)
            c1.cluster_id = _cluster_id(c1.canonical_name, c1.source_urls, c1.claims)

            logger.info(
                "entity_resolution.clusters_merged",
                merged_id=c1.cluster_id,
                name=c1.canonical_name,
                sources=len(c1.source_urls),
                score=best_score,
            )

            clusters.pop(j)
            merged = True

    # 3. Score each final cluster against target_name and hints
    for c in clusters:
        name_sim = _name_similarity(target_name, c.canonical_name)
        base_score = 0.50 + (0.35 * name_sim)

        # Multi-source corroboration boost
        if len(c.source_urls) >= 2:
            base_score += 0.15

        # Hint alignment if provided
        if hints:
            hint_org = getattr(hints, "organization", None) or (hints.get("organization") if isinstance(hints, dict) else None)
            if hint_org:
                orgs = _extract_orgs(c.claims)
                norm_hint_org = _normalize_org(hint_org)
                if any(norm_hint_org in o or o in norm_hint_org for o in orgs):
                    base_score += 0.15
                elif orgs:
                    base_score -= 0.20

            hint_role = getattr(hints, "role", None) or (hints.get("role") if isinstance(hints, dict) else None)
            if hint_role:
                occ = _extract_occupations(c.claims)
                norm_hint_role = hint_role.lower().strip()
                if any(norm_hint_role in o or o in norm_hint_role for o in occ):
                    base_score += 0.10

        c.score = min(max(round(base_score, 3), 0.1), 0.99)
        c.signals["target_name_similarity"] = round(name_sim, 2)

    # 4. Partition into primaries and alternatives
    clusters.sort(key=lambda c: c.score, reverse=True)
    primaries: list[PersonCluster] = []
    alternatives: list[PersonCluster] = []

    for c in clusters:
        name_sim = _name_similarity(target_name, c.canonical_name)
        if c.score >= threshold and name_sim >= 0.5:
            primaries.append(c)
        else:
            alternatives.append(c)

    logger.info(
        "entity_resolution.done",
        total_clusters=len(clusters),
        primaries=len(primaries),
        alternatives=len(alternatives),
    )

    return primaries, alternatives
