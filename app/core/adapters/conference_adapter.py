"""
Conference & Academic Proceedings Adapter.

Searches academic conference proceedings and speaker directories for a named
person, returning a CollectedSource that feeds both claim extraction and
cross-link signal detection for entity resolution.

Targeted sources:
  - ACM Digital Library (dl.acm.org) — public author search API
  - IEEE Xplore (ieeexplore.ieee.org) — public metadata API (no key for basic search)
  - Semantic Scholar author search already covers many conferences; this adapter
    targets proceedings/speaker pages that Semantic Scholar misses:
      AfricaComm, IEEE AFRICON, KICTANET, e-Government Kenya, etc.
  - DBLP computer science bibliography (dblp.org) — public XML/JSON API

Cross-link extraction (feeds entity resolution Task 4):
  When a conference page lists a speaker and links their:
    - GitHub profile
    - ORCID record
    - Institutional page
    - LinkedIn profile
  Those URLs are extracted as ``profile_url`` claims, creating cross-links
  between sources that the entity resolution cross-link signal can score.

TODO (you):
  Complete every section marked ``# TODO``.

Claim types produced:
  - publication  (paper/talk title, year)
  - organization (affiliation listed alongside the speaker/author)
  - role         ("speaker", "panelist", "session chair", "keynote speaker")
  - education    (degree listed on a speaker bio)
  - profile_url  (links to GitHub, ORCID, institutional page found on the page)
"""

import asyncio
import time
import urllib.parse
from typing import Any

import httpx
import structlog

from app.core.collector import CollectedSource

logger = structlog.get_logger(__name__)

_TIMEOUT = 20.0
_MAX_RESULTS = 20

# ACM DL author search (no key required for metadata)
ACM_AUTHOR_SEARCH = "https://dl.acm.org/action/doSearch"
ACM_AUTHOR_PROFILE = "https://dl.acm.org/profile/{acm_id}"

# IEEE Xplore metadata API
IEEE_SEARCH_URL = "https://ieeexplore.ieee.org/rest/search"

# DBLP JSON API
DBLP_SEARCH_URL = "https://dblp.org/search/publ/api"
DBLP_AUTHOR_URL = "https://dblp.org/search/author/api"


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_acm_results(
    name: str,
    *,
    client: httpx.AsyncClient,
    max_results: int = _MAX_RESULTS,
) -> list[dict[str, Any]]:
    """
    Search ACM Digital Library for conference papers by author name.

    Returns a list of dicts with keys:
      ``title``, ``authors``, ``venue``, ``year``, ``doi``, ``url``,
      ``affiliation``, ``profile_urls`` (list of external links found on the page).

    TODO:
      1. GET ACM_AUTHOR_SEARCH with params:
            AllField={url_encoded_name}&expand=dl&startPage=0&pageSize={max_results}
         and header ``Accept: application/json`` (ACM returns JSON for API requests).
      2. Parse the ``items`` list in the response. Each item has:
           - ``title``
           - ``authors`` (list of dicts with ``name`` and ``affiliation``)
           - ``publicationDate`` → extract year
           - ``doi`` → build URL as f"https://dl.acm.org/doi/{doi}"
           - ``proceedings`` or ``journal`` → conference/venue name
      3. Filter to results where the person's name appears in ``authors``.
      4. For each matching author entry, note the ``affiliation`` if present.
      5. Return [] on error.
    """
    results: list[dict[str, Any]] = []
    try:
        # TODO: implement ACM DL search.
        pass
    except Exception as exc:
        logger.error("conference_adapter.acm_error", name=name[:60], error=str(exc))
    return results


async def _fetch_ieee_results(
    name: str,
    *,
    client: httpx.AsyncClient,
    max_results: int = _MAX_RESULTS,
) -> list[dict[str, Any]]:
    """
    Search IEEE Xplore for conference papers by author name.

    Returns a list of dicts (same schema as _fetch_acm_results).

    TODO:
      1. GET IEEE_SEARCH_URL with params:
            querytext=Author:{name}&newsearch=true&pageNumber=1&rowsPerPage={max_results}
         and header ``Accept: application/json``.
      2. Parse ``articles`` list in the JSON response. Each article has:
           - ``title``
           - ``authors.authors`` → list of author objects with ``full_name`` and ``affiliation``
           - ``publication_year``
           - ``doi`` → URL: f"https://doi.org/{doi}"
           - ``publication_title`` → conference/journal name
      3. Filter to results where the person's name appears in the authors list.
      4. Return [] on error.
    """
    results: list[dict[str, Any]] = []
    try:
        # TODO: implement IEEE Xplore search.
        pass
    except Exception as exc:
        logger.error("conference_adapter.ieee_error", name=name[:60], error=str(exc))
    return results


async def _fetch_dblp_results(
    name: str,
    *,
    client: httpx.AsyncClient,
    max_results: int = _MAX_RESULTS,
) -> list[dict[str, Any]]:
    """
    Search DBLP bibliography for conference papers by author name.

    Returns a list of dicts (same schema as _fetch_acm_results).

    TODO:
      1. First search for the author:
            GET DBLP_AUTHOR_URL?q={name}&format=json&h=5
         Parse ``result.hits.hit`` list; each hit has ``info.author`` and ``info.url``.
      2. For each matching DBLP author URL, fetch their publications:
            GET {author_url}.json (DBLP returns JSON for .json suffix)
         Parse ``result.hits.hit`` list for conference papers
         (``info.type`` == "Conference and Workshop Papers").
      3. For each publication, build a result dict with:
           ``title``, ``authors``, ``venue``, ``year``, ``url``.
      4. Trim to max_results total. Return [] on error.
    """
    results: list[dict[str, Any]] = []
    try:
        # TODO: implement DBLP search (two-step: author lookup then publications).
        pass
    except Exception as exc:
        logger.error("conference_adapter.dblp_error", name=name[:60], error=str(exc))
    return results


def _extract_profile_urls(result: dict[str, Any]) -> list[str]:
    """
    Extract external profile URLs (GitHub, ORCID, institutional) from a
    conference result dict. These become ``profile_url`` claims in the
    CollectedSource text, which the entity resolution cross-link signal scores.

    TODO:
      Parse ``result.get("profile_urls", [])`` (a list of strings).
      Filter to URLs that match known profile domains:
        - github.com
        - orcid.org
        - linkedin.com/in/
        - *.ac.ke, *.edu, *.go.ke (institutional pages)
      Return the filtered list.
    """
    # TODO: implement filter.
    return result.get("profile_urls", [])


def _render_text(name: str, results: list[dict]) -> str:
    """
    Render a plain-text listing of conference papers for the named person.

    Format per result:
      "Conference paper: {title} ({year}). Venue: {venue}.
       Authors: {authors_string}. Affiliation: {affiliation}.
       URL: {url}. [Profile links: {profile_urls_csv}]"

    The ``Profile links`` segment is critical — it lets the LLM extraction
    produce ``profile_url`` claims that become cross-link evidence.

    TODO: implement render. Return "" if results is empty.
    """
    if not results:
        return ""

    lines = [
        f"Conference and academic proceedings for: {name}",
        f"Total results: {len(results)}",
        "",
    ]
    for r in results:
        # TODO: format each result dict into the line format described above.
        pass

    return "\n".join(lines)


def _deduplicate(results: list[dict]) -> list[dict]:
    """
    Deduplicate results by DOI (preferred) then by normalised title.

    TODO:
      Keep the first occurrence of each (doi or normalised_title).
      Return the deduplicated list.
    """
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[dict] = []
    for r in results:
        doi = (r.get("doi") or "").strip().lower()
        title_norm = (r.get("title") or "").strip().lower()
        if doi and doi in seen_dois:
            continue
        if title_norm and title_norm in seen_titles:
            continue
        if doi:
            seen_dois.add(doi)
        if title_norm:
            seen_titles.add(title_norm)
        deduped.append(r)
    return deduped


# ── Public API ────────────────────────────────────────────────────────────────

async def fetch_conference_papers(
    name: str,
    *,
    organization_hint: str = "",
    country_hint: str = "",
    max_results: int = _MAX_RESULTS,
) -> CollectedSource | None:
    """
    Search conference databases for the named person and return a CollectedSource.

    Args:
        name: The author/speaker's full name.
        organization_hint: Optional affiliation to prefer/filter results.
        country_hint: Optional country to scope the search.
        max_results: Maximum number of results to include.

    Returns:
        CollectedSource or None if no results found.

    TODO:
      1. Run _fetch_acm_results, _fetch_ieee_results, _fetch_dblp_results
         concurrently with asyncio.gather.
      2. Combine all results and call _deduplicate.
      3. If organization_hint is given, sort results so affiliation-matching
         entries come first (don't discard unmatched).
      4. Trim to max_results.
      5. Call _render_text. If empty, return None.
      6. Build the CollectedSource:
           - url: DBLP author page URL if found, else ACM/IEEE search URL.
           - domain: "dblp.org" (or whichever source was most fruitful).
           - source_type: "conference_paper"
           - title: f"Conference papers: {name}"
           - text: rendered text
           - retrieved_at: time.time()
           - status_code: 200
      7. Log "conference_adapter.fetched" with counts per source.
    """
    log = logger.bind(name=name)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        acm_res, ieee_res, dblp_res = await asyncio.gather(
            _fetch_acm_results(name, client=client, max_results=max_results),
            _fetch_ieee_results(name, client=client, max_results=max_results),
            _fetch_dblp_results(name, client=client, max_results=max_results),
            return_exceptions=True,
        )

    # Flatten — gather may return exceptions if something raises unexpectedly
    all_results: list[dict] = []
    for batch in (acm_res, ieee_res, dblp_res):
        if isinstance(batch, list):
            all_results.extend(batch)
        else:
            logger.error("conference_adapter.gather_error", error=str(batch))

    all_results = _deduplicate(all_results)

    # TODO: apply organization_hint sorting (see docstring step 3).

    all_results = all_results[:max_results]

    text = _render_text(name, all_results)
    if not text.strip():
        log.info("conference_adapter.no_results")
        return None

    # TODO: prefer the DBLP author URL if available (from _fetch_dblp_results results).
    encoded = urllib.parse.quote(name)
    url = f"https://dblp.org/search?q={encoded}"
    domain = "dblp.org"

    log.info(
        "conference_adapter.fetched",
        total=len(all_results),
        acm=len(acm_res) if isinstance(acm_res, list) else 0,
        ieee=len(ieee_res) if isinstance(ieee_res, list) else 0,
        dblp=len(dblp_res) if isinstance(dblp_res, list) else 0,
    )

    return CollectedSource(
        url=url,
        domain=domain,
        source_type="conference_paper",
        title=f"Conference papers: {name}",
        text=text,
        retrieved_at=time.time(),
        status_code=200,
    )
