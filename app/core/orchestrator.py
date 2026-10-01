"""
Search Orchestrator.

Coordinates the full pipeline for a single search request:
  1. Query understanding  (AI-assisted name parsing)
  2. Audit logging        (query stored BEFORE any data is fetched)
  3. Candidate discovery  (find candidate URLs for the name)
  4. Source collection    (fetch pages — robots-aware, throttled)
  5. Snippet fallback     (for candidates that couldn't be fetched, use
                           the search-engine snippet as a lightweight source)
  6. Extraction           (LLM → claims, span-verified, scope-filtered)
  7. Entity resolution    (deterministic clustering)
  8. Profile assembly     (build the API response)

The orchestrator is intentionally thin — each step is a separate module.
"""

import time
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.model_adapter import ModelAdapter
from app.core.collector import collect_sources, CollectedSource
from app.core.discovery import discover_candidates, get_search_provider, CandidateURL
from app.core.entity_resolution import resolve_entities
from app.core.extraction import extract_claims
from app.core.persistence import persist_cluster
from app.core.query_understanding import understand_query, QueryContext
from app.schemas.search import ClaimOut, EvidenceItem, PersonResult, SearchRequest, SearchResponse
from app.models.governance import Query as QueryModel

logger = structlog.get_logger(__name__)


async def _log_query(
    db: AsyncSession,
    request: SearchRequest,
    context: QueryContext,
    user_id: str | None,
) -> uuid.UUID:
    """Persist an audit record before any search work begins."""
    record = QueryModel(
        user_id=user_id,
        input_json={
            "name": request.name,
            "hints": request.hints.model_dump(exclude_none=True),
            "canonical_name": context.canonical_name,
            "name_variants": context.name_variants,
        },
        purpose=request.purpose,
    )
    db.add(record)
    await db.flush()  # get the generated ID without committing
    return record.id


def _snippet_source(candidate: CandidateURL) -> CollectedSource:
    """
    Synthesise a lightweight CollectedSource from a search engine snippet.

    Used when the page collector couldn't fetch the full page (e.g. LinkedIn
    blocks bots). The snippet is short but still contains name, role, and
    employer text that the LLM can extract claims from.
    """
    return CollectedSource(
        url=candidate.url,
        domain=candidate.url.split("/")[2] if "//" in candidate.url else candidate.url,
        source_type=candidate.source_type,
        title=f"Search snippet: {candidate.url}",
        text=candidate.snippet,
        retrieved_at=time.time(),
        status_code=0,   # 0 = snippet-only, not a full page fetch
    )


async def run_search(
    request: SearchRequest,
    db: AsyncSession,
    adapter: ModelAdapter,
    user_id: str | None = None,
) -> SearchResponse:
    """
    Execute the full search pipeline and return a SearchResponse.

    Each stage is logged. Errors in non-critical stages are caught and
    logged so a single bad source never kills the entire search.
    """
    log = logger.bind(name=request.name, user_id=user_id)
    log.info("orchestrator.search.start")

    # ── 1. Query understanding ─────────────────────────────────────────────────
    context = await understand_query(request, adapter)
    log.info("orchestrator.query_understood", canonical=context.canonical_name)

    # ── 2. Audit log (before any data is fetched) ──────────────────────────────
    query_id = await _log_query(db, request, context, user_id)
    log = log.bind(query_id=str(query_id))

    # ── 3. Candidate discovery ────────────────────────────────────────────────
    provider = get_search_provider()
    candidates: list[CandidateURL] = await discover_candidates(
        context=context,
        provider=provider,
        max_candidates=20,
    )
    log.info("orchestrator.discovery.done", candidates=len(candidates))

    # ── 4. Source collection ──────────────────────────────────────────────────
    sources: list[CollectedSource] = await collect_sources(
        urls=[(c.url, c.source_type) for c in candidates],
        max_concurrent=5,
    )
    log.info("orchestrator.collection.done", sources=len(sources))

    # ── 5. Snippet fallback ───────────────────────────────────────────────────
    # For any candidate whose page we couldn't fetch, synthesise a source from
    # the search-engine snippet (short but often contains name + role + employer).
    fetched_urls = {s.url for s in sources}
    snippet_sources: list[CollectedSource] = []
    for candidate in candidates:
        if candidate.url not in fetched_urls and candidate.snippet:
            snippet_sources.append(_snippet_source(candidate))

    all_sources = sources + snippet_sources
    log.info(
        "orchestrator.sources.total",
        fetched=len(sources),
        snippet_fallbacks=len(snippet_sources),
        total=len(all_sources),
    )

    # ── 6. Extraction (per source, concurrent) ────────────────────────────────
    # Sources are extracted concurrently (up to 5 in parallel) so that the
    # pipeline doesn't block on sequential AI calls.
    # A failure on any single source is caught and logged — it never halts the pipeline.
    import asyncio as _asyncio

    extract_semaphore = _asyncio.Semaphore(5)

    async def _extract_one(source: CollectedSource) -> dict | None:
        if not source.text or len(source.text.strip()) < 10:
            return None
        async with extract_semaphore:
            try:
                raw_claims = await extract_claims(
                    source_url=source.url,
                    source_text=source.text,
                    target_name=context.canonical_name,
                    source_id=source.url,
                    adapter=adapter,
                )
            except Exception as exc:
                log.error("orchestrator.extraction.error", url=source.url, error=str(exc))
                raw_claims = []

        if not raw_claims:
            return None
        return {
            "url": source.url,
            "name_on_source": context.canonical_name,
            "claims": [
                {**c, "source_url": source.url, "source_type": source.source_type}
                for c in raw_claims
            ],
        }

    extraction_results = await _asyncio.gather(
        *[_extract_one(s) for s in all_sources],
        return_exceptions=True,
    )
    candidate_results: list[dict] = [
        r for r in extraction_results
        if isinstance(r, dict) and r is not None
    ]
    log.info("orchestrator.extraction.done", sources_with_claims=len(candidate_results))

    # ── 7. Entity resolution ──────────────────────────────────────────────────
    primaries, alternatives = resolve_entities(
        candidate_claim_sets=candidate_results,
        target_name=context.canonical_name,
    )
    log.info("orchestrator.resolution.done", primaries=len(primaries), alternatives=len(alternatives))

    # ── 8. Claim persistence ──────────────────────────────────────────────────
    # Save extracted claims + sources to the database after resolution.
    sources_by_url = {s.url: s for s in all_sources}

    # Persist alternative clusters first to generate real Person IDs
    alt_ids: list[uuid.UUID] = []
    for alt_cluster in alternatives:
        try:
            alt_person = await persist_cluster(
                cluster=alt_cluster,
                collected_sources=sources_by_url,
                db=db,
            )
            if alt_person:
                alt_ids.append(alt_person.id)
        except Exception as exc:
            log.error("orchestrator.persist.alt.error", error=str(exc))

    # Persist primary clusters and assemble response
    results: list[PersonResult] = []
    for cluster in primaries:
        try:
            person = await persist_cluster(
                cluster=cluster,
                collected_sources=sources_by_url,
                db=db,
            )
        except Exception as exc:
            log.error("orchestrator.persist.primary.error", error=str(exc))
            person = None

        if person is None:
            # Suppressed identity — skip entirely
            continue

        # Build claim output — include ALL claims, using uuid4 as fallback claim_id
        # so the response is never silently empty.
        claims_out = [
            ClaimOut(
                claim_id=c.get("claim_id") or uuid.uuid4(),
                type=c.get("claim_type", ""),
                value=c.get("value", ""),
                confidence=c.get("confidence", cluster.score),
                evidence=[
                    EvidenceItem(
                        source_url=c.get("source_url", ""),
                        source_type=c.get("source_type", ""),
                        excerpt=c.get("evidence_span", ""),
                        retrieved_at=datetime.now(timezone.utc),
                    )
                ],
            )
            for c in cluster.claims
            if c.get("value")  # only drop claims with no value at all
        ]
        results.append(
            PersonResult(
                person_id=person.id,
                label="possible match",
                confidence=cluster.score,
                canonical_name=cluster.canonical_name,
                claims=claims_out,
                alternatives=alt_ids,
            )
        )

    log.info("orchestrator.search.done", result_count=len(results))
    return SearchResponse(
        query_id=query_id,
        results=results,
        parsed_hints=context.model_dump(),
    )
