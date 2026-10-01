"""
Candidate Discovery module.

Takes a QueryContext and returns a ranked list of candidate URLs for the
search orchestrator to collect and extract from.

Design:
  - Provider-agnostic: a SearchProvider ABC lets us swap DuckDuckGo,
    Google Custom Search, Bing, Serper, etc. with no upstream changes.
  - Source-type allowlist: discovered URLs are matched against the
    ALLOWED_SOURCE_TYPES registry. Any URL that doesn't resolve to
    a recognised source type is dropped before collection.
  - No PII is stored here — only the URL and inferred source type.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urlparse

import structlog

from app.core.query_understanding import QueryContext

logger = structlog.get_logger(__name__)


# ── Source-type allowlist ──────────────────────────────────────────────────────
# Maps a domain pattern (regex) to a source_type label.
# Only URLs that match at least one entry are collected.
# Add entries here as new source types are approved.

@dataclass
class SourceTypeRule:
    pattern: re.Pattern
    source_type: str


_SOURCE_TYPE_RULES: list[SourceTypeRule] = [
    # LinkedIn — match /in/ profiles and country subdomains (ke.linkedin.com, etc.)
    SourceTypeRule(re.compile(r"linkedin\.com/(in/|pub/dir/)"),   "linkedin_profile"),
    SourceTypeRule(re.compile(r"github\.com/[^/]+$"),             "github_profile"),
    SourceTypeRule(re.compile(r"github\.com/[^/]+/[^/]+"),        "github_repo"),
    SourceTypeRule(re.compile(r"twitter\.com/|x\.com/"),          "twitter_profile"),
    SourceTypeRule(re.compile(r"scholar\.google\.com"),           "google_scholar"),
    SourceTypeRule(re.compile(r"orcid\.org/"),                    "orcid_profile"),
    SourceTypeRule(re.compile(r"researchgate\.net/profile"),      "researchgate_profile"),
    SourceTypeRule(re.compile(r"academia\.edu/"),                 "academia_profile"),
    SourceTypeRule(re.compile(r"patents\.google\.com"),           "patent"),
    SourceTypeRule(re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov"),    "publication"),
    SourceTypeRule(re.compile(r"arxiv\.org/"),                    "publication"),
    SourceTypeRule(re.compile(r"ssrn\.com/"),                     "publication"),
    SourceTypeRule(re.compile(r"speakerdeck\.com/|slideshare\.net/"), "talk"),
    # Professional directories
    SourceTypeRule(re.compile(r"crunchbase\.com/person"),         "directory_profile"),
    SourceTypeRule(re.compile(r"bloomberg\.com/profile"),         "directory_profile"),
    SourceTypeRule(re.compile(r"getprog\.ai/profile"),            "directory_profile"),
    SourceTypeRule(re.compile(r"zoominfo\.com/"),                 "directory_profile"),
    SourceTypeRule(re.compile(r"about\.me/"),                     "directory_profile"),
    SourceTypeRule(re.compile(r"gravatar\.com/"),                 "directory_profile"),
    # Company / organisation pages — broad match, refined by source collector
    SourceTypeRule(re.compile(r"/team|/staff|/about|/people|/leadership"), "company_page"),
    # Conference & university pages
    SourceTypeRule(re.compile(r"\.edu/|conference|proceedings|symposium"), "conference_or_university"),
    # Press — broad; collector will check robots.txt
    SourceTypeRule(re.compile(r"techcrunch|wired\.com|bloomberg\.com|reuters|nation\.co\.ke|businessdailyafrica|standardmedia"), "press"),
]


@dataclass
class CandidateURL:
    url: str
    source_type: str
    rank: int          # lower = higher priority
    snippet: str = ""  # search engine snippet, used as a candidate hint


def classify_url(url: str) -> str | None:
    """Return the source_type for a URL, or None if not on the allowlist."""
    for rule in _SOURCE_TYPE_RULES:
        if rule.pattern.search(url):
            return rule.source_type
    return None


def _deduplicate(candidates: list[CandidateURL]) -> list[CandidateURL]:
    """Remove duplicate URLs, keeping the highest-ranked occurrence."""
    seen: set[str] = set()
    out: list[CandidateURL] = []
    for c in sorted(candidates, key=lambda x: x.rank):
        if c.url not in seen:
            seen.add(c.url)
            out.append(c)
    return out


# ── Search provider ABC ────────────────────────────────────────────────────────

class SearchProvider(ABC):
    """
    Abstract base for all search backends.

    Implementations must be stateless and async. Each provider is
    responsible for its own auth, pagination, and error handling.
    Return at most `limit` results — callers do not paginate.
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Return a list of dicts, each with at least:
          { "url": str, "title": str, "snippet": str }
        """
        ...


class DuckDuckGoProvider(SearchProvider):
    """
    DuckDuckGo search provider.

    Uses the `ddgs` library (install: pip install ddgs). No API key required.
    Falls back gracefully if the library is unavailable.
    """

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        # Try the new `ddgs` package first, then the legacy `duckduckgo_search`
        DDGS_cls = None
        try:
            from ddgs import DDGS as _DDGS  # type: ignore
            DDGS_cls = _DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS as _DDGS2  # type: ignore
                DDGS_cls = _DDGS2
            except ImportError:
                logger.warning("discovery.ddgs_not_installed", hint="pip install ddgs")
                return []

        try:
            results = []
            with DDGS_cls() as ddgs:
                for r in ddgs.text(query, max_results=limit):
                    results.append({
                        "url": r.get("href", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                    })
            logger.info("discovery.ddgs_results", query=query[:60], count=len(results))
            return results
        except Exception as exc:
            logger.error("discovery.ddgs_error", error=str(exc))
            return []


class SerperProvider(SearchProvider):
    """
    Serper.dev Google Search API provider.

    Requires SERPER_API_KEY in environment / settings.
    Add `serper_api_key: str = ""` to Settings when enabling.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        import httpx
        if not self._api_key:
            logger.warning("discovery.serper_no_key")
            return []
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": self._api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": limit},
                )
                resp.raise_for_status()
                data = resp.json()
                return [
                    {
                        "url": r.get("link", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                    }
                    for r in data.get("organic", [])
                ]
            except Exception as exc:
                logger.error("discovery.serper_error", error=str(exc))
                return []


# ── Discovery orchestrator ─────────────────────────────────────────────────────

def _build_queries(context: QueryContext) -> list[str]:
    """
    Build a list of search queries from the QueryContext.

    We issue one query per name variant (capped) plus one with the
    primary name + each hint. This maximises recall without hammering
    the search provider.
    """
    queries: list[str] = []
    hints = context.hints

    # Base queries — one per name variant (cap at 3 to limit API calls)
    for name in [context.canonical_name] + context.name_variants[:2]:
        q = f'"{name}"'
        if hints.get("organization"):
            q += f' "{hints["organization"]}"'
        if hints.get("country"):
            q += f' {hints["country"]}'
        if hints.get("role"):
            q += f' "{hints["role"]}"'
        queries.append(q)

    # Extra targeted queries for strong profile sources
    base = f'"{context.canonical_name}"'
    queries.append(f'site:linkedin.com/in/ {base}')
    queries.append(f'site:github.com {base}')

    return list(dict.fromkeys(queries))  # deduplicate while preserving order


async def discover_candidates(
    context: QueryContext,
    provider: SearchProvider,
    max_candidates: int = 20,
) -> list[CandidateURL]:
    """
    Run discovery queries and return allowlisted, deduplicated candidate URLs.

    Args:
        context: Parsed query context from the query understanding stage.
        provider: A SearchProvider implementation.
        max_candidates: Hard cap on the number of candidates returned.

    Returns:
        List of CandidateURL objects, sorted by rank (best first).
    """
    queries = _build_queries(context)
    raw_results: list[dict] = []

    for i, query in enumerate(queries):
        logger.info("discovery.query", query=query, index=i)
        results = await provider.search(query, limit=10)
        # Tag each result with the query index so we can use it for ranking
        for r in results:
            r["_query_index"] = i
        raw_results.extend(results)

    # Classify and filter against the source-type allowlist
    candidates: list[CandidateURL] = []
    for rank, result in enumerate(raw_results):
        url = result.get("url", "").strip()
        if not url:
            continue
        source_type = classify_url(url)
        if source_type is None:
            logger.debug("discovery.url_not_allowlisted", url=url)
            continue
        candidates.append(
            CandidateURL(
                url=url,
                source_type=source_type,
                rank=rank,
                snippet=result.get("snippet", ""),
            )
        )

    deduped = _deduplicate(candidates)[:max_candidates]
    logger.info(
        "discovery.done",
        name=context.canonical_name,
        raw=len(raw_results),
        allowlisted=len(candidates),
        after_dedup=len(deduped),
    )
    return deduped


# ── Provider factory ───────────────────────────────────────────────────────────

def get_search_provider() -> SearchProvider:
    """
    Return the configured search provider.

    Priority:
      1. If SERPER_API_KEY is set → SerperProvider (better quality)
      2. Otherwise → DuckDuckGoProvider (no key, free)
    """
    import os
    serper_key = os.getenv("SERPER_API_KEY", "")
    if serper_key:
        logger.info("discovery.provider", provider="serper")
        return SerperProvider(api_key=serper_key)
    logger.info("discovery.provider", provider="duckduckgo")
    return DuckDuckGoProvider()
