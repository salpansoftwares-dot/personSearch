"""
PubMed / NCBI E-utilities adapter.

Uses the NCBI E-utilities API to search for publications by author name and
return a structured CollectedSource.

API docs: https://www.ncbi.nlm.nih.gov/books/NBK25499/
No API key required (rate-limited to 3 req/s without key, 10 req/s with key).
"""

import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx
import structlog

from app.core.collector import CollectedSource

logger = structlog.get_logger(__name__)

PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_TIMEOUT = 15.0
_MAX_RESULTS = 20
_TOOL = "PersonSearch"
_EMAIL = "ops@personsearch.example"  # required by NCBI for attribution


async def _esearch(
    query: str,
    *,
    client: httpx.AsyncClient,
    max_results: int = _MAX_RESULTS,
) -> list[str]:
    """
    Run an esearch query and return a list of PubMed IDs.
    """
    try:
        resp = await client.get(
            PUBMED_ESEARCH,
            params={
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "tool": _TOOL,
                "email": _EMAIL,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("esearchresult", {}).get("idlist", []) or []
    except Exception as exc:
        logger.error("pubmed_adapter.esearch_error", query=query[:80], error=str(exc))
        return []


async def _efetch_summaries(
    pmids: list[str],
    *,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """
    Fetch article summaries for a list of PubMed IDs.
    Returns a list of dicts with title, authors, journal, year, abstract.
    """
    if not pmids:
        return []
    try:
        resp = await client.get(
            PUBMED_EFETCH,
            params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "xml",
                "rettype": "abstract",
                "tool": _TOOL,
                "email": _EMAIL,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return _parse_pubmed_xml(resp.text)
    except Exception as exc:
        logger.error("pubmed_adapter.efetch_error", pmids=pmids[:5], error=str(exc))
        return []


def _parse_pubmed_xml(xml_text: str) -> list[dict[str, Any]]:
    """
    Parse PubMed XML efetch response into a list of article dicts.
    """
    articles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    for article_elem in root.findall(".//PubmedArticle"):
        try:
            # Title
            title_elem = article_elem.find(".//ArticleTitle")
            title = (title_elem.text or "").strip() if title_elem is not None else ""

            # Journal
            journal_elem = article_elem.find(".//Journal/Title")
            journal = (journal_elem.text or "").strip() if journal_elem is not None else ""

            # Year
            year_elem = article_elem.find(".//PubDate/Year")
            year = (year_elem.text or "").strip() if year_elem is not None else ""

            # Authors
            authors = []
            for a in article_elem.findall(".//Author"):
                last = (a.findtext("LastName") or "").strip()
                fore = (a.findtext("ForeName") or a.findtext("Initials") or "").strip()
                if last:
                    authors.append(f"{fore} {last}".strip())

            # Abstract
            abstract_texts = []
            for ab in article_elem.findall(".//AbstractText"):
                label = ab.get("Label", "")
                text = (ab.text or "").strip()
                if text:
                    abstract_texts.append(f"{label}: {text}" if label else text)
            abstract = " ".join(abstract_texts)

            if title:
                articles.append({
                    "title": title,
                    "authors": authors,
                    "journal": journal,
                    "year": year,
                    "abstract": abstract[:500],
                })
        except Exception:
            continue

    return articles


def _render_text(name: str, articles: list[dict]) -> str:
    """
    Render a plain-text summary of PubMed results for the named author.
    """
    if not articles:
        return ""

    lines = [f"PubMed publications by author: {name}"]
    lines.append(f"Total results shown: {len(articles)}")
    lines.append("Publications:")
    for a in articles:
        entry = f"  - {a['title']}"
        if a.get("year"):
            entry += f" ({a['year']})"
        if a.get("journal"):
            entry += f", {a['journal']}"
        author_str = ", ".join(a.get("authors", [])[:5])
        if author_str:
            entry += f". Authors: {author_str}"
        if a.get("abstract"):
            entry += f". Abstract: {a['abstract']}"
        lines.append(entry)
    return "\n".join(lines)


async def fetch_pubmed_author(
    name: str,
    *,
    organization_hint: str = "",
    country_hint: str = "",
    max_papers: int = _MAX_RESULTS,
) -> CollectedSource | None:
    """
    Search PubMed for publications by the named author and return a CollectedSource.

    Args:
        name: The author's full name.
        organization_hint: Optional affiliation to narrow results.
        country_hint: Optional country to narrow results.
        max_papers: Maximum number of papers to fetch.

    Returns:
        CollectedSource or None if no results or API error.
    """
    from app.core.country_utils import parse_country

    log = logger.bind(name=name)

    # Build query: author name with optional affiliation
    query = f'"{name}"[Author]'
    if organization_hint:
        query += f' AND "{organization_hint}"[Affiliation]'
    elif country_hint:
        country_info = parse_country(country_hint)
        country_term = country_info.name if country_info else country_hint
        query += f' AND "{country_term}"[Affiliation]'

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        pmids = await _esearch(query, client=client, max_results=max_papers)

        if not pmids:
            log.info("pubmed_adapter.no_results", query=query)
            return None

        articles = await _efetch_summaries(pmids, client=client)

    if not articles:
        log.info("pubmed_adapter.no_articles_parsed")
        return None

    text = _render_text(name, articles)
    if not text.strip():
        return None

    url = f"https://pubmed.ncbi.nlm.nih.gov/?term={name.replace(' ', '+')}%5BAuthor%5D"
    log.info(
        "pubmed_adapter.fetched",
        articles=len(articles),
        text_chars=len(text),
    )

    return CollectedSource(
        url=url,
        domain="pubmed.ncbi.nlm.nih.gov",
        source_type="publication",
        title=f"PubMed publications: {name}",
        text=text,
        retrieved_at=time.time(),
        status_code=200,
    )
