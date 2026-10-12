"""
Patents Adapter.

Searches public patent databases for patents listing the named person as an
inventor and returns a structured CollectedSource.

Targeted sources:
  - Google Patents (patents.google.com) — JSON API via Serper/SerpAPI or
    direct search scrape (check TOS and robots.txt).
  - WIPO PatentScope (patsearch.wipo.int) — public JSON API, no key required.
  - Kenya Industrial Property Institute (KIPI) — (kipi.go.ke) public search.

TODO (lameckkipsang):
  Complete every section marked ``# TODO``. Do NOT remove any ``# TODO`` comment
  until the implementation it describes is finished and the tests pass.

Claim types produced by this adapter (must stay on the allowlist):
  - publication  (patent title, year — use "publication" as per the data model)
  - organization (assignee / applicant organisation)
  - role         ("inventor" or "co-inventor" as listed on the patent)

⚠️ Architecture rules:
  1. Only extract what the patent document explicitly states. Never infer a
     person's home address, email, or personal data from patent records.
  2. Never claim the person "is" an inventor without a verbatim evidence_span
     from the patent text (the extraction pipeline enforces this, but keep the
     text rich enough for the LLM to find a real span).
  3. If no results, return None.

WIPO PatentScope simple API example (no key needed):
  GET https://patsearch.wipo.int/api/en/search?query=inventor:"{name}"&rows=10
  Returns JSON with ``docs`` list, each having ``title``, ``inventor``,
  ``applicant``, ``publicationDate``, ``url``.
"""

import time
import urllib.parse
from typing import Any

import httpx
import structlog

from app.core.collector import CollectedSource

logger = structlog.get_logger(__name__)

_TIMEOUT = 20.0
_MAX_RESULTS = 15

WIPO_SEARCH_URL = "https://patsearch.wipo.int/api/en/search"
GOOGLE_PATENTS_SEARCH = "https://patents.google.com/xhr/query"

# TODO: Add KIPI endpoint once you confirm the public search URL.
KIPI_SEARCH_URL = "https://kipi.go.ke/search?type=patent&inventor={query}"


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_wipo_patents(
    name: str,
    *,
    client: httpx.AsyncClient,
    max_results: int = _MAX_RESULTS,
) -> list[dict[str, Any]]:
    """
    Search WIPO PatentScope for patents by inventor name.

    Returns a list of patent dicts with keys:
      ``title``, ``inventors``, ``applicants``, ``publication_date``, ``patent_number``, ``url``.

    TODO (lameckkipsang):
      1. Build the query params:
            {
              "query": f'inventor:"{name}"',
              "rows": max_results,
              "start": 0,
              "fields": "title,inventor,applicant,publicationDate,patentNumber,url"
            }
      2. Issue a GET to WIPO_SEARCH_URL with those params.
      3. Parse the JSON response. The ``docs`` list contains the results.
         Each doc has (inspect the real response — keys may differ slightly):
           - ``title``       → patent title
           - ``inventor``    → list of inventor names (may be a string or list)
           - ``applicant``   → list of applicant/assignee names
           - ``publicationDate`` → "YYYY-MM-DD" string
           - ``patentNumber`` → e.g. "WO2024/123456"
           - ``url``         → direct WIPO record URL
      4. Filter results to only include those where the person's name appears
         in the ``inventor`` field (case-insensitive partial match is fine).
      5. Return the filtered list. Return [] on error.
    """
    results: list[dict[str, Any]] = []
    try:
        # TODO: implement the search described above.
        pass
    except Exception as exc:
        logger.error("patents_adapter.wipo_error", name=name[:60], error=str(exc))
    return results


async def _fetch_google_patents(
    name: str,
    *,
    client: httpx.AsyncClient,
    max_results: int = _MAX_RESULTS,
) -> list[dict[str, Any]]:
    """
    Search Google Patents for patents by inventor name.

    Returns a list of patent dicts with the same schema as _fetch_wipo_patents.

    TODO (lameckkipsang):
      Option A (preferred if you have a SerpAPI key in settings):
        Use the SerpAPI Google Patents endpoint:
          GET https://serpapi.com/search.json
             ?engine=google_patents
             &q=inventor:"{name}"
             &api_key={settings.serpapi_key}
             &num={max_results}
        Parse ``organic_results`` from the JSON response.

      Option B (no API key — direct scrape):
        GET https://patents.google.com/xhr/query
           ?url=q%3Dinventor%3A{url_encoded_name}&exp=&download=false&ajax=true
        Parse the JSON ``results.cluster`` array.

      In both cases, filter for results listing the person as an inventor and
      return the same dict schema. Return [] on any error.
    """
    results: list[dict[str, Any]] = []
    try:
        # TODO: implement one of the two options described above.
        pass
    except Exception as exc:
        logger.error("patents_adapter.google_error", name=name[:60], error=str(exc))
    return results


async def _fetch_kipi_patents(
    name: str,
    *,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """
    Search the Kenya Industrial Property Institute (KIPI) for patents.

    Returns a list of patent dicts (same schema as above).

    TODO (lameckkipsang):
      1. Issue a GET to KIPI_SEARCH_URL.format(query=...) with the name URL-encoded.
      2. Parse the HTML/JSON response (inspect the real KIPI site to determine format).
      3. Extract patent/utility-model records where the person is listed as inventor.
      4. Return [] on error. Log errors via structlog.
    """
    results: list[dict[str, Any]] = []
    try:
        # TODO: implement KIPI scrape.
        pass
    except Exception as exc:
        logger.error("patents_adapter.kipi_error", name=name[:60], error=str(exc))
    return results


def _render_text(name: str, patents: list[dict]) -> str:
    """
    Render a plain-text listing of patents for the named inventor.

    The text is consumed by the LLM extraction step to produce structured claims.
    Each patent entry should be on its own line and include enough context for
    the LLM to quote a real evidence span.

    Format per patent:
      "Patent: {title} ({year}). Inventor: {inventors}. Assignee: {applicants}.
       Patent number: {patent_number}. Published: {publication_date}."

    TODO (lameckkipsang):
      Build the rendered string from the patents list. Return "" if patents is empty.
    """
    if not patents:
        return ""

    lines = [f"Patents listing inventor: {name}", f"Total found: {len(patents)}", ""]

    for p in patents:
        # TODO: build a formatted line for each patent dict.
        pass

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

async def fetch_patents(
    name: str,
    *,
    organization_hint: str = "",
    country_hint: str = "",
    max_results: int = _MAX_RESULTS,
) -> CollectedSource | None:
    """
    Search patent databases for the named inventor and return a CollectedSource.

    Args:
        name: The inventor's full name.
        organization_hint: Optional assignee/applicant to narrow results.
        country_hint: Optional country code or name (e.g. "KE", "Kenya").
        max_results: Maximum number of patents to fetch per source.

    Returns:
        CollectedSource or None if no patents found.

    TODO (lameckkipsang):
      1. Run _fetch_wipo_patents, _fetch_google_patents, _fetch_kipi_patents
         concurrently with asyncio.gather.
      2. Deduplicate results by patent_number (case-insensitive).
      3. If organization_hint is provided, prefer patents where the assignee
         matches (move to front of list, don't discard unmatched ones).
      4. Trim to max_results.
      5. Call _render_text. If empty, return None.
      6. Return CollectedSource with:
           - url: f"https://patsearch.wipo.int/en/search?inventor={url_encoded_name}"
           - domain: "patsearch.wipo.int"
           - source_type: "patent"
           - title: f"Patents — inventor: {name}"
           - text: rendered text
           - retrieved_at: time.time()
           - status_code: 200
      7. Log "patents_adapter.fetched" with count.
    """
    log = logger.bind(name=name)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # TODO: gather results from all three sources concurrently.
        all_patents: list[dict] = []

    text = _render_text(name, all_patents)
    if not text.strip():
        log.info("patents_adapter.no_results")
        return None

    encoded = urllib.parse.quote(name)
    url = f"https://patsearch.wipo.int/en/search?inventor={encoded}"

    log.info("patents_adapter.fetched", count=len(all_patents))

    return CollectedSource(
        url=url,
        domain="patsearch.wipo.int",
        source_type="patent",
        title=f"Patents — inventor: {name}",
        text=text,
        retrieved_at=time.time(),
        status_code=200,
    )
