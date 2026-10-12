"""
University & Professional Registry Adapter.

Searches university faculty/profile pages and Kenyan professional registry
directories for a named person and returns a structured CollectedSource.

Targeted sources:
  - East African university profile directories (.ac.ke, .edu)
  - Kenya Medical Practitioners & Dentists Council (KMPDC)
  - Law Society of Kenya (LSK) member directory
  - Institution of Engineers of Kenya (IEK) member search
  - Engineers Board of Kenya (EBK)

TODO (lameckkipsang):
  Complete every section marked ``# TODO``. Do NOT remove any ``# TODO`` comment
  until the implementation it describes is finished and the tests pass.

Claim types produced by this adapter (must stay on the allowlist):
  - occupation
  - organization
  - education
  - role
  - profile_url

API key / auth requirements:
  - University pages: public HTML — use httpx GET + BeautifulSoup (already a dep).
  - KMPDC / LSK / IEK: scrape public search pages (check robots.txt first).
  - Respect per-domain throttling; see collector.py for the _DOMAIN_SEMAPHORES pattern.

Architecture rules:
  1. Only return claim types on the allowlist (scope_filter.py enforces this, but
     don't produce out-of-scope fields here either).
  2. Never return home address, phone, personal email, biometric data.
  3. Every CollectedSource must have a real ``url`` and ``retrieved_at``.
  4. If no results are found, return None (not an empty CollectedSource).
"""

import time
from typing import Any

import httpx
import structlog

from app.core.collector import CollectedSource

logger = structlog.get_logger(__name__)

_TIMEOUT = 15.0
_MAX_RESULTS = 10

# University profile base URLs to search.
# TODO: expand this list with more East African university directories.
_UNIVERSITY_SEARCH_URLS: list[dict[str, str]] = [
    {
        "name": "University of Nairobi",
        "search_url": "https://profiles.uonbi.ac.ke/search/node/{query}",
        "domain": "profiles.uonbi.ac.ke",
    },
    {
        "name": "Strathmore University",
        "search_url": "https://www.strathmore.edu/search?q={query}",
        "domain": "www.strathmore.edu",
    },
    # TODO: Add Kenyatta University, JKUAT, Moi University, USIU-Africa,
    #        University of Dar es Salaam, Makerere University, etc.
]

# Professional registry search endpoints.
# TODO: Fill in real search endpoints once scraped / documented.
_REGISTRY_SEARCH_URLS: list[dict[str, str]] = [
    {
        "name": "KMPDC",
        "search_url": "https://kmpdc.go.ke/registers/search?name={query}",
        "domain": "kmpdc.go.ke",
        "claim_type": "occupation",  # e.g. "Registered Medical Practitioner"
    },
    {
        "name": "LSK",
        "search_url": "https://lsk.or.ke/members/?s={query}",
        "domain": "lsk.or.ke",
        "claim_type": "occupation",
    },
    {
        "name": "EBK",
        "search_url": "https://ebk.go.ke/registered-engineers/?search={query}",
        "domain": "ebk.go.ke",
        "claim_type": "occupation",
    },
    # TODO: Add IEK, Nursing Council of Kenya, CPA Kenya (ICPAK), etc.
]


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_university_results(
    name: str,
    *,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """
    Search university profile directories for a person by name.

    Returns a list of result dicts with keys: ``name``, ``role``, ``org``,
    ``url``, ``source_name``.

    TODO (lameckkipsang):
      1. For each entry in _UNIVERSITY_SEARCH_URLS, issue a GET request to
         the search URL with the person's name substituted for ``{query}``.
      2. Parse the HTML response with BeautifulSoup (``from bs4 import BeautifulSoup``).
      3. Extract result entries — typically ``<a>`` tags inside a results list or
         faculty card grid. Each entry should yield: display name, role/title,
         department/organization, and profile page URL.
      4. Follow the profile URL if needed to extract more structured data.
      5. Return a list of result dicts for each found entry.
      6. Respect robots.txt: check ``/robots.txt`` for each domain before scraping.
      7. Return [] (not raise) on any HTTP / parse error — log via structlog.
    """
    results: list[dict[str, Any]] = []

    for univ in _UNIVERSITY_SEARCH_URLS:
        url = univ["search_url"].format(query=name.replace(" ", "+"))
        try:
            # TODO: implement the HTTP GET + HTML parsing described above.
            pass
        except Exception as exc:
            logger.error(
                "university_adapter.fetch_error",
                source=univ["name"],
                error=str(exc),
            )

    return results


async def _fetch_registry_results(
    name: str,
    *,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """
    Search Kenyan professional registry pages for a person by name.

    Returns a list of result dicts with keys: ``name``, ``registry``,
    ``registration_number`` (optional), ``claim_type``, ``url``.

    TODO (lameckkipsang):
      1. For each entry in _REGISTRY_SEARCH_URLS, issue a GET to the search URL
         with ``{query}`` replaced by the URL-encoded person name.
      2. Parse the HTML with BeautifulSoup. Look for result rows/cards containing
         the person's name (case-insensitive substring match is acceptable).
      3. Extract registration_number, role/profession, and the result page URL.
      4. Return [] on errors — never raise.
    """
    results: list[dict[str, Any]] = []

    for registry in _REGISTRY_SEARCH_URLS:
        url = registry["search_url"].format(query=name.replace(" ", "+"))
        try:
            # TODO: implement the HTTP GET + HTML parsing described above.
            pass
        except Exception as exc:
            logger.error(
                "university_adapter.registry_fetch_error",
                registry=registry["name"],
                error=str(exc),
            )

    return results


def _render_text(
    name: str,
    university_results: list[dict],
    registry_results: list[dict],
) -> str:
    """
    Render a plain-text summary of university and registry results.

    The text is what the LLM extraction step will read to produce structured
    claims. Make it dense, factual, and structured — one line per result.

    TODO (lameckkipsang):
      Build the text string from the two result lists:
        - For each university result: "{name} — {role} at {org} ({source_name})"
        - For each registry result:  "{name} — registered {registry} professional
          (reg. no. {registration_number})" if available, else just the registry name.
      Return "" (empty string) if both lists are empty.
    """
    lines: list[str] = []

    if not university_results and not registry_results:
        return ""

    lines.append(f"University and registry search results for: {name}")

    # TODO: render university_results
    if university_results:
        lines.append("University profiles:")
        for r in university_results:
            # TODO: format each result
            pass

    # TODO: render registry_results
    if registry_results:
        lines.append("Professional registry records:")
        for r in registry_results:
            # TODO: format each result
            pass

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

async def fetch_university_and_registry(
    name: str,
    *,
    organization_hint: str = "",
    country_hint: str = "",
) -> CollectedSource | None:
    """
    Search university directories and Kenyan professional registries for the
    named person and return a CollectedSource.

    Args:
        name: The person's full name (required).
        organization_hint: Optional institution name to prefer/filter results.
        country_hint: Optional country to scope the search (default: Kenya / East Africa).

    Returns:
        CollectedSource or None if no results or all sources errored.

    TODO (lameckkipsang):
      1. Call ``_fetch_university_results`` and ``_fetch_registry_results``.
      2. Optionally filter by ``organization_hint`` if provided (case-insensitive
         substring match on the ``org`` field of each result).
      3. Call ``_render_text`` to build the text payload.
      4. If text is empty, return None.
      5. Construct and return the CollectedSource with:
           - url: a sensible canonical URL (e.g. the first result's profile URL,
             or a search results URL).
           - domain: the domain of that URL.
           - source_type: "university_page"
           - title: f"University/Registry profiles: {name}"
           - text: the rendered text.
           - retrieved_at: time.time()
           - status_code: 200
      6. Log a structured log line: "university_adapter.fetched" with counts.
    """
    log = logger.bind(name=name)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # TODO: call _fetch_university_results and _fetch_registry_results in parallel
        #       using asyncio.gather for performance.
        university_results: list[dict] = []
        registry_results: list[dict] = []

    text = _render_text(name, university_results, registry_results)
    if not text.strip():
        log.info("university_adapter.no_results")
        return None

    # TODO: pick a real URL from the first result or build a search-results URL.
    url = f"https://profiles.uonbi.ac.ke/search/node/{name.replace(' ', '+')}"
    domain = "profiles.uonbi.ac.ke"

    log.info(
        "university_adapter.fetched",
        university_hits=len(university_results),
        registry_hits=len(registry_results),
    )

    return CollectedSource(
        url=url,
        domain=domain,
        source_type="university_page",
        title=f"University/Registry profiles: {name}",
        text=text,
        retrieved_at=time.time(),
        status_code=200,
    )
