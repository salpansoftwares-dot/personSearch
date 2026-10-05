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
from app.core.adapters.orcid_adapter import find_orcid_ids_for_name, fetch_orcid_profile
from app.core.adapters.semantic_scholar_adapter import fetch_semantic_scholar_author
from app.core.adapters.pubmed_adapter import fetch_pubmed_author
from app.core.summarizer import generate_profile_summary
from app.core.conflict_detector import detect_conflicts_and_staleness


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
        max_candidates=10,
    )
    log.info("orchestrator.discovery.done", candidates=len(candidates))

    # ── 4 & 4a. Source collection & API adapters in parallel ──────────────────
    import asyncio as _asyncio

    org_hint = context.hints.get("organization", "") or ""
    country_hint = context.hints.get("country", "") or ""

    async def _run_api_adapters() -> list[CollectedSource]:
        adapter_sources: list[CollectedSource] = []

        async def _safe(coro):
            try:
                return await coro
            except Exception as exc:
                log.error("orchestrator.adapter.error", error=str(exc))
                return None

        # Run ORCID, Semantic Scholar, and PubMed in parallel
        orcid_ids = await _safe(
            find_orcid_ids_for_name(
                context.canonical_name,
                organization_hint=org_hint,
                country_hint=country_hint,
                max_results=1,
            )
        ) or []

        orcid_tasks = [
            _safe(fetch_orcid_profile(oid, name_hint=context.canonical_name))
            for oid in orcid_ids[:1]
        ]
        s2_task = _safe(
            fetch_semantic_scholar_author(
                context.canonical_name,
                organization_hint=org_hint,
                country_hint=country_hint,
                max_candidates=1,
            )
        )
        pm_task = _safe(
            fetch_pubmed_author(
                context.canonical_name,
                organization_hint=org_hint,
                country_hint=country_hint,
            )
        )

        all_adapter_tasks = orcid_tasks + [s2_task, pm_task]
        adapter_results = await _asyncio.gather(*all_adapter_tasks)
        for r in adapter_results:
            if isinstance(r, list):
                adapter_sources.extend(r)
            elif isinstance(r, CollectedSource):
                adapter_sources.append(r)

        return adapter_sources

    # Run web collection and API adapters concurrently!
    web_collection_task = collect_sources(
        urls=[(c.url, c.source_type) for c in candidates],
        max_concurrent=6,
    )
    sources, api_adapter_sources = await _asyncio.gather(
        web_collection_task,
        _run_api_adapters(),
    )
    log.info("orchestrator.collection.done", web_sources=len(sources), api_sources=len(api_adapter_sources))

    # ── 5. Snippet fallback & source prioritization ───────────────────────────
    fetched_urls = {s.url for s in sources} | {s.url for s in api_adapter_sources}
    snippet_sources: list[CollectedSource] = []
    for candidate in candidates:
        if candidate.url not in fetched_urls and candidate.snippet:
            snippet_sources.append(_snippet_source(candidate))

    # Merge: Prioritize structured API adapters + verified fetched web sources
    _seen_urls: set[str] = set()
    all_sources: list[CollectedSource] = []
    for s in api_adapter_sources + sources + snippet_sources:
        if s.url not in _seen_urls:
            _seen_urls.add(s.url)
            all_sources.append(s)

    # Cap to top 12 high-quality sources for extraction
    all_sources = all_sources[:12]

    log.info(
        "orchestrator.sources.total",
        fetched=len(sources),
        api_adapters=len(api_adapter_sources),
        snippet_fallbacks=len(snippet_sources),
        selected=len(all_sources),
    )



    # ── 6. Extraction (per source, concurrent) ────────────────────────────────
    # Sources are extracted concurrently (up to 5 in parallel) so that the
    # pipeline doesn't block on sequential AI calls.
    # A failure on any single source is caught and logged — it never halts the pipeline.
    import asyncio as _asyncio

    extract_semaphore = _asyncio.Semaphore(10)

    async def _extract_one(source: CollectedSource) -> dict | None:
        if not source.text or len(source.text.strip()) < 10:
            return None
        async with extract_semaphore:
            try:
                raw_claims = await extract_claims(
                    source_url=source.url,
                    source_text=source.text[:6000],
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
        hints=request.hints,
    )
    log.info("orchestrator.resolution.done", primaries=len(primaries), alternatives=len(alternatives))

    # If primaries is empty but alternatives exist, promote the top alternative
    if not primaries and alternatives:
        primaries = [alternatives.pop(0)]

    # ── 8. Claim persistence & response assembly ─────────────────────────────
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

    # Persist primary clusters
    primary_records: list[tuple[PersonCluster, Person]] = []
    for cluster in primaries:
        try:
            person = await persist_cluster(
                cluster=cluster,
                collected_sources=sources_by_url,
                db=db,
            )
            if person:
                primary_records.append((cluster, person))
        except Exception as exc:
            log.error("orchestrator.persist.primary.error", error=str(exc))

    all_primary_ids = [p.id for _, p in primary_records]

    # Process primary profile summaries concurrently in parallel
    async def _build_primary(cluster: PersonCluster, person: Person) -> PersonResult:
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
            if c.get("value")
        ]

        calibrated_claims, conflict_flags, staleness_flags = detect_conflicts_and_staleness(claims_out)

        summary = await generate_profile_summary(
            canonical_name=cluster.canonical_name,
            claims=calibrated_claims,
            adapter=adapter,
        )
        if summary and summary.sentences:
            try:
                person.summary_json = summary.model_dump(mode="json")
                await db.flush()
            except Exception as exc:
                log.warning("orchestrator.save_summary.failed", error=str(exc))

        other_alts = [pid for pid in all_primary_ids if pid != person.id] + alt_ids

        return PersonResult(
            person_id=person.id,
            label="possible match",
            confidence=cluster.score,
            canonical_name=cluster.canonical_name,
            claims=calibrated_claims,
            summary=summary if (summary and summary.sentences) else None,
            conflict_flags=conflict_flags,
            staleness_flags=staleness_flags,
            alternatives=other_alts,
        )

    primary_tasks = [_build_primary(c, p) for c, p in primary_records]
    results = await _asyncio.gather(*primary_tasks)


    log.info("orchestrator.search.done", result_count=len(results))
    return SearchResponse(
        query_id=query_id,
        results=results,
        parsed_hints=context.model_dump(),
    )
