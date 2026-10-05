"""
Semantic Scholar Public API adapter.

Fetches author profiles and paper lists from the Semantic Scholar Academic Graph API.
No API key required for basic usage (rate-limited to 100 req/5 min without a key).

API docs: https://api.semanticscholar.org/graph/v1
"""

import time
from typing import Any

import httpx
import structlog

from app.core.collector import CollectedSource

logger = structlog.get_logger(__name__)

S2_API_BASE = "https://api.semanticscholar.org/graph/v1"
_TIMEOUT = 15.0
_MAX_PAPERS = 20


async def _search_author(
    name: str,
    *,
    client: httpx.AsyncClient,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """
    Search for authors by name and return the top candidates.
    """
    try:
        resp = await client.get(
            f"{S2_API_BASE}/author/search",
            params={
                "query": name,
                "limit": limit,
                "fields": "authorId,name,affiliations,paperCount,hIndex",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", []) or []
    except Exception as exc:
        logger.error("semantic_scholar.search_error", name=name, error=str(exc))
        return []


async def _fetch_author_papers(
    author_id: str,
    *,
    client: httpx.AsyncClient,
    limit: int = _MAX_PAPERS,
) -> list[dict[str, Any]]:
    """
    Fetch papers for an author by their S2 authorId.
    """
    try:
        resp = await client.get(
            f"{S2_API_BASE}/author/{author_id}/papers",
            params={
                "limit": limit,
                "fields": "title,year,venue,authors",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", []) or []
    except Exception as exc:
        logger.error("semantic_scholar.papers_error", author_id=author_id, error=str(exc))
        return []


def _render_text(
    author_id: str,
    name: str,
    affiliations: list[str],
    paper_count: int,
    h_index: int,
    papers: list[dict],
) -> str:
    """
    Render a plain-text summary of the Semantic Scholar author record.
    The text must be readable prose so the LLM can find verbatim evidence spans.
    """
    lines = [f"Semantic Scholar author profile: {name} (ID: {author_id})"]
    if affiliations:
        lines.append(f"Affiliations: {', '.join(affiliations)}")
    if paper_count:
        lines.append(f"Total papers: {paper_count}")
    if h_index:
        lines.append(f"h-index: {h_index}")
    if papers:
        lines.append("Recent publications:")
        for p in papers:
            title = p.get("title", "").strip()
            year = p.get("year") or ""
            venue = p.get("venue", "").strip()
            if title:
                entry = f"  - {title}"
                if year:
                    entry += f" ({year})"
                if venue:
                    entry += f", published in {venue}"
                lines.append(entry)
    return "\n".join(lines)


async def fetch_semantic_scholar_author(
    name: str,
    *,
    organization_hint: str = "",
    country_hint: str = "",
    max_candidates: int = 1,
) -> list[CollectedSource]:
    """
    Search Semantic Scholar for authors matching the name and return
    CollectedSources for the top matches.

    Args:
        name: The author's name to search for.
        organization_hint: Optional affiliation to improve matching.
        country_hint: Optional country code or name to restrict results.
        max_candidates: Maximum number of author profiles to return.

    Returns:
        List of CollectedSource (may be empty if no match or API error).
    """
    from app.core.country_utils import parse_country, text_matches_country, text_conflicts_with_country

    log = logger.bind(name=name)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        candidates = await _search_author(name, client=client, limit=max_candidates + 4)

    if not candidates:
        log.info("semantic_scholar.no_candidates")
        return []

    country_info = parse_country(country_hint) if country_hint else None

    # Filter by organization hint if provided
    if organization_hint:
        org_lower = organization_hint.lower()
        matching_org = [
            c for c in candidates
            if any(org_lower in aff.lower() for aff in (c.get("affiliations") or []))
        ]
        if matching_org:
            candidates = matching_org
        else:
            # Candidates with known conflicting affiliations should be dropped when an org hint was explicitly given
            candidates = [c for c in candidates if not c.get("affiliations")]

    # Filter by country hint if provided
    if country_info and candidates:
        matching_country = []
        for c in candidates:
            aff_str = " ".join(c.get("affiliations") or [])
            if text_matches_country(aff_str, country_info):
                matching_country.append(c)
            else:
                is_conf, _ = text_conflicts_with_country(aff_str, country_info)
                if not is_conf:
                    matching_country.append(c)
        if matching_country:
            candidates = matching_country

    sources: list[CollectedSource] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for candidate in candidates[:max_candidates]:
            author_id = candidate.get("authorId", "")
            author_name = candidate.get("name", name)
            affiliations = candidate.get("affiliations") or []
            paper_count = candidate.get("paperCount") or 0
            h_index = candidate.get("hIndex") or 0

            papers = await _fetch_author_papers(author_id, client=client)

            text = _render_text(
                author_id=author_id,
                name=author_name,
                affiliations=affiliations,
                paper_count=paper_count,
                h_index=h_index,
                papers=papers,
            )

            if not text.strip():
                continue

            url = f"https://www.semanticscholar.org/author/{author_id}"
            log.info(
                "semantic_scholar.fetched",
                author_id=author_id,
                author_name=author_name,
                papers=len(papers),
                text_chars=len(text),
            )

            sources.append(CollectedSource(
                url=url,
                domain="semanticscholar.org",
                source_type="publication",
                title=f"Semantic Scholar: {author_name}",
                text=text,
                retrieved_at=time.time(),
                status_code=200,
            ))

    return sources
