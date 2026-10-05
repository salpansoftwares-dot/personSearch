"""
ORCID Public API adapter.

Fetches a researcher's public ORCID record using the ORCID public API
(no authentication required for public records). Returns a CollectedSource
whose text is a structured plain-text rendering of the ORCID record, safe
for claim extraction.

ORCID API docs: https://pub.orcid.org/v3.0/
"""

import time
from typing import Any

import httpx
import structlog

from app.core.collector import CollectedSource

logger = structlog.get_logger(__name__)

ORCID_API_BASE = "https://pub.orcid.org/v3.0"
ORCID_ACCEPT_HEADER = "application/json"
_TIMEOUT = 15.0


def _extract_name(record: dict) -> str:
    """Pull the full name from the ORCID person block."""
    try:
        person = record.get("person", {})
        name_block = person.get("name", {}) or {}
        given = (name_block.get("given-names", {}) or {}).get("value", "") or ""
        family = (name_block.get("family-name", {}) or {}).get("value", "") or ""
        return f"{given} {family}".strip()
    except Exception:
        return ""


def _extract_biography(record: dict) -> str:
    try:
        person = record.get("person", {})
        bio = person.get("biography", {}) or {}
        return (bio.get("content") or "").strip()
    except Exception:
        return ""


def _extract_employments(record: dict) -> list[dict[str, str]]:
    """Return a list of {organization, role, start, end} dicts."""
    results = []
    try:
        acts = record.get("activities-summary", {}) or {}
        emp_group = (acts.get("employments", {}) or {}).get("affiliation-group", []) or []
        for group in emp_group:
            summaries = group.get("summaries", []) or []
            for s in summaries:
                es = s.get("employment-summary", {}) or {}
                org = ((es.get("organization", {}) or {}).get("name") or "").strip()
                role = (es.get("role-title") or "").strip()
                start_year = str(
                    ((es.get("start-date", {}) or {}).get("year", {}) or {}).get("value", "") or ""
                )
                end_year = str(
                    ((es.get("end-date", {}) or {}).get("year", {}) or {}).get("value", "") or ""
                )
                if org:
                    results.append({"organization": org, "role": role,
                                    "start": start_year, "end": end_year})
    except Exception:
        pass
    return results


def _extract_educations(record: dict) -> list[dict[str, str]]:
    results = []
    try:
        acts = record.get("activities-summary", {}) or {}
        edu_group = (acts.get("educations", {}) or {}).get("affiliation-group", []) or []
        for group in edu_group:
            summaries = group.get("summaries", []) or []
            for s in summaries:
                es = s.get("education-summary", {}) or {}
                org = ((es.get("organization", {}) or {}).get("name") or "").strip()
                role = (es.get("role-title") or "").strip()
                if org:
                    results.append({"organization": org, "degree": role})
    except Exception:
        pass
    return results


def _extract_works(record: dict) -> list[str]:
    """Return a list of publication titles (up to 20)."""
    titles = []
    try:
        acts = record.get("activities-summary", {}) or {}
        work_groups = (acts.get("works", {}) or {}).get("group", []) or []
        for group in work_groups[:20]:
            summaries = group.get("work-summary", []) or []
            for ws in summaries[:1]:  # first summary per group is best
                t = (ws.get("title", {}) or {}).get("title", {}) or {}
                title = (t.get("value") or "").strip()
                if title:
                    titles.append(title)
    except Exception:
        pass
    return titles


def _render_text(orcid_id: str, name: str, bio: str,
                 employments: list, educations: list, works: list) -> str:
    """
    Render a plain-text summary of the ORCID record.

    This is what gets passed to the LLM for claim extraction.
    It must be readable prose so the LLM can find verbatim evidence spans.
    """
    lines = [f"ORCID profile: {orcid_id}"]
    if name:
        lines.append(f"Name: {name}")
    if bio:
        lines.append(f"Biography: {bio}")
    if employments:
        lines.append("Employment history:")
        for e in employments:
            entry = f"  - {e['role']} at {e['organization']}" if e.get("role") else f"  - {e['organization']}"
            if e.get("start"):
                entry += f" ({e['start']}–{e.get('end', 'present')})"
            lines.append(entry)
    if educations:
        lines.append("Education:")
        for e in educations:
            entry = f"  - {e['degree']} at {e['organization']}" if e.get("degree") else f"  - {e['organization']}"
            lines.append(entry)
    if works:
        lines.append("Publications / works:")
        for w in works:
            lines.append(f"  - {w}")
    return "\n".join(lines)


async def fetch_orcid_profile(
    orcid_id: str,
    *,
    name_hint: str = "",
) -> CollectedSource | None:
    """
    Fetch an ORCID public profile by ORCID iD and return a CollectedSource.

    Args:
        orcid_id: The 16-digit ORCID iD, e.g. "0000-0002-1825-0097".
        name_hint: The target person's name (used for logging).

    Returns:
        CollectedSource or None if the fetch fails.
    """
    url = f"https://orcid.org/{orcid_id}"
    api_url = f"{ORCID_API_BASE}/{orcid_id}"
    log = logger.bind(orcid_id=orcid_id, name_hint=name_hint)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                api_url,
                headers={"Accept": ORCID_ACCEPT_HEADER},
                follow_redirects=True,
            )
            if resp.status_code == 404:
                log.warning("orcid_adapter.not_found")
                return None
            resp.raise_for_status()
            record: dict[str, Any] = resp.json()

    except httpx.HTTPStatusError as exc:
        log.error("orcid_adapter.http_error", status=exc.response.status_code)
        return None
    except Exception as exc:
        log.error("orcid_adapter.error", error=str(exc))
        return None

    name = _extract_name(record) or name_hint
    bio = _extract_biography(record)
    employments = _extract_employments(record)
    educations = _extract_educations(record)
    works = _extract_works(record)

    text = _render_text(orcid_id, name, bio, employments, educations, works)
    if not text.strip():
        log.warning("orcid_adapter.empty_record")
        return None

    log.info(
        "orcid_adapter.fetched",
        name=name,
        employments=len(employments),
        works=len(works),
        text_chars=len(text),
    )

    return CollectedSource(
        url=url,
        domain="orcid.org",
        source_type="orcid_profile",
        title=f"ORCID profile: {name or orcid_id}",
        text=text,
        retrieved_at=time.time(),
        status_code=200,
    )


async def find_orcid_ids_for_name(
    name: str,
    *,
    organization_hint: str = "",
    country_hint: str = "",
    max_results: int = 3,
) -> list[str]:
    """
    Search the ORCID public API for records matching a name.

    Returns a list of ORCID iDs (up to max_results).
    """
    from app.core.country_utils import parse_country

    query = f'"{name}"'
    if organization_hint:
        query += f' AND affiliation-org-name:"{organization_hint}"'
    if country_hint:
        country_info = parse_country(country_hint)
        if country_info:
            query += f' AND (address-country-code:"{country_info.code.upper()}" OR affiliation-org-name:"{country_info.name}")'

    params = {
        "q": query,
        "rows": max_results,
        "start": 0,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{ORCID_API_BASE}/search",
                params=params,
                headers={"Accept": ORCID_ACCEPT_HEADER},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("orcid_adapter.search_error", name=name, error=str(exc))
        return []

    orcid_ids = []
    try:
        results = data.get("result", []) or []
        for r in results:
            orcid_id_obj = (r.get("orcid-identifier") or {}).get("path")
            if orcid_id_obj:
                orcid_ids.append(orcid_id_obj)
    except Exception:
        pass

    logger.info("orcid_adapter.search_done", name=name, found=len(orcid_ids))
    return orcid_ids
