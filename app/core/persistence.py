"""
Persistence layer — saves pipeline results to the database.

After the extraction + entity resolution stages, this module writes:
  - sources         → one row per collected URL
  - claims          → one row per verified, in-scope claim
  - persons         → one row per resolved cluster (upsert by canonical name)
  - person_claims   → junction linking each person to their claims
  - person_names    → all name variants seen for the person

Design rules:
  - All writes for one search run happen in a single transaction.
    If anything fails, nothing is persisted (no partial state).
  - Claims are separated from persons so they can be re-attributed
    if a cluster is split or corrected later.
  - Suppression check: suppressed identities are never written.
  - Idempotent source upsert: if the same URL was already collected
    recently, we reuse the existing source row.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.claim import Claim, ClaimType
from app.models.governance import Suppression
from app.models.person import Person, PersonClaim, PersonName, PersonStatus
from app.models.source import Source
from app.core.entity_resolution import PersonCluster

logger = structlog.get_logger(__name__)


# ── Suppression check ──────────────────────────────────────────────────────────

def _suppression_key(name: str) -> str:
    """Canonical suppression key — SHA-256 of lowercased name."""
    return hashlib.sha256(name.strip().lower().encode()).hexdigest()


async def is_suppressed(name: str, db: AsyncSession) -> bool:
    """Return True if this identity is on the suppression list or marked suppressed."""
    key = _suppression_key(name)
    result = await db.execute(
        select(Suppression).where(Suppression.match_key == key).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        logger.warning("persistence.suppressed", name=name, reason="suppression_table")
        return True

    person_res = await db.execute(
        select(Person)
        .where(Person.canonical_name == name)
        .where(Person.status == PersonStatus.suppressed)
        .limit(1)
    )
    if person_res.scalar_one_or_none() is not None:
        logger.warning("persistence.suppressed", name=name, reason="person_suppressed")
        return True

    return False


# ── Source upsert ──────────────────────────────────────────────────────────────

async def upsert_source(
    *,
    url: str,
    domain: str,
    title: str,
    source_type: str,
    db: AsyncSession,
) -> Source:
    """
    Insert or return an existing Source row for this URL.

    Uses ON CONFLICT DO NOTHING so re-collecting the same URL within
    the expiry window just reuses the existing row.
    """
    stmt = (
        pg_insert(Source)
        .values(
            url=url,
            domain=domain,
            title=title or "",
            source_type=source_type,
            retrieved_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["url"])
        .returning(Source.id)
    )
    result = await db.execute(stmt)
    source_id = result.scalar_one_or_none()

    if source_id is not None:
        # Freshly inserted
        result2 = await db.execute(select(Source).where(Source.id == source_id))
        source = result2.scalar_one()
    else:
        # Already existed — look it up
        existing = await db.execute(select(Source).where(Source.url == url))
        source = existing.scalar_one()

    logger.debug("persistence.source_upserted", url=url, source_id=str(source.id))
    return source


# ── Claim insertion ────────────────────────────────────────────────────────────

async def insert_claim(
    *,
    source: Source,
    claim_type: str,
    value: str,
    evidence_span: str,
    confidence: float,
    db: AsyncSession,
) -> Claim | None:
    """
    Insert a single claim row, or return an existing identical claim for this source.

    Returns None and logs a warning if claim_type is not in the allowlist
    (this is a second-pass guard — scope_filter should have caught it first).
    """
    try:
        ct = ClaimType(claim_type)
    except ValueError:
        logger.warning(
            "persistence.claim_type_invalid",
            claim_type=claim_type,
            value=value,
        )
        return None

    # Check if identical claim already exists for this source
    existing = await db.execute(
        select(Claim).where(
            Claim.source_id == source.id,
            Claim.claim_type == ct.value,
            Claim.value == value,
        ).limit(1)
    )
    claim = existing.scalar_one_or_none()
    if claim is None:
        claim = Claim(
            source_id=source.id,
            claim_type=ct.value,
            value=value,
            evidence_span=evidence_span,
            confidence=confidence,
        )
        db.add(claim)
        await db.flush()  # get the ID without committing
        logger.debug(
            "persistence.claim_inserted",
            claim_id=str(claim.id),
            type=claim_type,
            value=value[:60],
        )
    else:
        logger.debug(
            "persistence.claim_reused",
            claim_id=str(claim.id),
            type=claim_type,
            value=value[:60],
        )
    return claim


# ── Person upsert ──────────────────────────────────────────────────────────────

async def upsert_person(
    *,
    canonical_name: str,
    db: AsyncSession,
) -> Person:
    """
    Get or create a Person row for the given canonical name.

    We deliberately do NOT merge on every search — a new cluster only
    gets its own row. Merging existing rows is handled by the merge_log
    module (future). This keeps the default-to-unmerged principle intact.
    """
    result = await db.execute(
        select(Person)
        .where(Person.canonical_name == canonical_name)
        .where(Person.status == PersonStatus.active)
        .limit(1)
    )
    person = result.scalar_one_or_none()

    if person is None:
        person = Person(
            canonical_name=canonical_name,
            status=PersonStatus.active,
        )
        db.add(person)
        await db.flush()
        logger.info("persistence.person_created", person_id=str(person.id), name=canonical_name)
    else:
        logger.debug("persistence.person_reused", person_id=str(person.id), name=canonical_name)

    return person


# ── Link person ↔ claim ────────────────────────────────────────────────────────

async def link_person_claim(
    *,
    person: Person,
    claim: Claim,
    link_confidence: float,
    link_reason: str,
    db: AsyncSession,
) -> None:
    """Create a PersonClaim junction row if it doesn't already exist."""
    existing = await db.execute(
        select(PersonClaim)
        .where(PersonClaim.person_id == person.id)
        .where(PersonClaim.claim_id == claim.id)
    )
    if existing.scalar_one_or_none() is None:
        junction = PersonClaim(
            person_id=person.id,
            claim_id=claim.id,
            link_confidence=link_confidence,
            link_reason=link_reason,
        )
        db.add(junction)
        await db.flush()


async def record_person_name(
    *,
    person: Person,
    name: str,
    claim: Claim | None,
    db: AsyncSession,
) -> None:
    """Record a name variant for a person if not already recorded."""
    existing = await db.execute(
        select(PersonName)
        .where(PersonName.person_id == person.id)
        .where(PersonName.name == name)
    )
    if existing.scalar_one_or_none() is None:
        pn = PersonName(
            person_id=person.id,
            name=name,
            claim_id=claim.id if claim else None,
        )
        db.add(pn)
        await db.flush()


# ── Top-level: persist a full cluster ─────────────────────────────────────────

async def persist_cluster(
    *,
    cluster: PersonCluster,
    collected_sources: dict,  # url → CollectedSource
    db: AsyncSession,
) -> Person | None:
    """
    Persist a single resolved PersonCluster to the database.

    Flow:
      1. Suppression check — skip entirely if suppressed.
      2. Upsert source rows.
      3. Insert claim rows (scope already validated upstream).
      4. Upsert person row.
      5. Link person ↔ claims (PersonClaim junction).
      6. Record name variants (PersonName).

    Returns the Person ORM object, or None if the cluster was suppressed.
    All writes are flushed but not committed — the caller controls the
    transaction boundary.
    """
    log = logger.bind(cluster_id=cluster.cluster_id, name=cluster.canonical_name)

    # ── 1. Suppression check ───────────────────────────────────────────────────
    if await is_suppressed(cluster.canonical_name, db):
        log.warning("persistence.cluster_suppressed")
        return None

    # ── 2. Upsert sources ──────────────────────────────────────────────────────
    all_source_urls = set(cluster.source_urls) | {
        c.get("source_url") for c in cluster.claims if c.get("source_url")
    }
    source_map: dict[str, Source] = {}
    for url in all_source_urls:
        cs = collected_sources.get(url)
        if cs is not None:
            source = await upsert_source(
                url=cs.url,
                domain=cs.domain,
                title=cs.title or "",
                source_type=cs.source_type,
                db=db,
            )
            source_map[url] = source
        else:
            existing = await db.execute(select(Source).where(Source.url == url).limit(1))
            source = existing.scalar_one_or_none()
            if source:
                source_map[url] = source
            else:
                domain = urlparse(url).netloc or "unknown"
                source_type = next(
                    (c.get("source_type") for c in cluster.claims if c.get("source_url") == url and c.get("source_type")),
                    "web_page",
                )
                source = await upsert_source(
                    url=url,
                    domain=domain,
                    title="",
                    source_type=source_type,
                    db=db,
                )
                source_map[url] = source

    # ── 3 & 4. Insert claims + create/link person ────────────────────────────
    if cluster.person_id:
        person_res = await db.execute(select(Person).where(Person.id == cluster.person_id))
        person = person_res.scalar_one_or_none()
        if person is None:
            person = Person(
                id=cluster.person_id,
                canonical_name=cluster.canonical_name,
                status=PersonStatus.active,
            )
            db.add(person)
            await db.flush()
    else:
        person = Person(
            canonical_name=cluster.canonical_name,
            status=PersonStatus.active,
        )
        db.add(person)
        await db.flush()
        cluster.person_id = person.id
    persisted_claims: list[Claim] = []

    for raw_claim in cluster.claims:
        source_url = raw_claim.get("source_url", "")
        source = source_map.get(source_url)
        if source is None:
            log.warning("persistence.claim_missing_source", source_url=source_url)
            continue

        claim = await insert_claim(
            source=source,
            claim_type=raw_claim.get("claim_type", ""),
            value=raw_claim.get("value", ""),
            evidence_span=raw_claim.get("evidence_span", ""),
            confidence=raw_claim.get("confidence", cluster.score),
            db=db,
        )
        if claim:
            persisted_claims.append(claim)
            raw_claim["claim_id"] = claim.id

    # ── 5. Link person ↔ claims ────────────────────────────────────────────────
    for claim in persisted_claims:
        await link_person_claim(
            person=person,
            claim=claim,
            link_confidence=cluster.score,
            link_reason=f"cluster_score={cluster.score:.3f}",
            db=db,
        )

    # ── 6. Name variants ───────────────────────────────────────────────────────
    await record_person_name(
        person=person,
        name=cluster.canonical_name,
        claim=persisted_claims[0] if persisted_claims else None,
        db=db,
    )
    for raw_claim in cluster.claims:
        if raw_claim.get("claim_type") == "name_variant":
            variant_name = raw_claim.get("value", "")
            if variant_name and variant_name != cluster.canonical_name:
                await record_person_name(
                    person=person,
                    name=variant_name,
                    claim=next((c for c in persisted_claims if c.value == variant_name), None),
                    db=db,
                )

    log.info(
        "persistence.cluster_persisted",
        person_id=str(person.id),
        claims=len(persisted_claims),
        sources=len(source_map),
    )
    return person


# ── Persist all clusters from a search run ────────────────────────────────────

async def persist_search_results(
    *,
    clusters: list[PersonCluster],
    collected_sources: dict,   # url → CollectedSource
    db: AsyncSession,
) -> list[Person]:
    """
    Persist all clusters from a search run.

    Returns the list of Person objects successfully written.
    Suppressed clusters are silently skipped.
    """
    persons: list[Person] = []
    for cluster in clusters:
        person = await persist_cluster(
            cluster=cluster,
            collected_sources=collected_sources,
            db=db,
        )
        if person:
            persons.append(person)

    logger.info(
        "persistence.search_results_persisted",
        clusters_in=len(clusters),
        persons_out=len(persons),
    )
    return persons
