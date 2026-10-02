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

    # ── V2: Additional academic sources ───────────────────────────────────────
    SourceTypeRule(re.compile(r"semanticscholar\.org/"),          "publication"),
    SourceTypeRule(re.compile(r"ieeexplore\.ieee\.org/"),         "publication"),
    SourceTypeRule(re.compile(r"dl\.acm\.org/"),                  "publication"),
    SourceTypeRule(re.compile(r"scholar\.archive\.org/"),         "publication"),
    SourceTypeRule(re.compile(r"europepmc\.org/"),                "publication"),
    SourceTypeRule(re.compile(r"worldcat\.org/"),                 "publication"),

    # ── V2: Kenyan professional / registry pages ───────────────────────────────
    SourceTypeRule(re.compile(r"ecitizen\.go\.ke/"),              "registry"),
    SourceTypeRule(re.compile(r"kenyalaw\.org/"),                 "registry"),
    SourceTypeRule(re.compile(r"nse\.co\.ke/"),                   "registry"),       # Nairobi Stock Exchange
    SourceTypeRule(re.compile(r"icpak\.com/"),                    "directory_profile"),  # CPA Kenya
    SourceTypeRule(re.compile(r"lsk\.or\.ke/"),                   "directory_profile"),  # Law Society of Kenya
    SourceTypeRule(re.compile(r"iea\.or\.ke/"),                   "directory_profile"),  # Engineers Kenya

    SourceTypeRule(re.compile(r"speakerdeck\.com/|slideshare\.net/"), "talk"),

    # Professional directories
    SourceTypeRule(re.compile(r"crunchbase\.com/person"),         "directory_profile"),
    SourceTypeRule(re.compile(r"bloomberg\.com/profile"),         "directory_profile"),
    SourceTypeRule(re.compile(r"getprog\.ai/profile"),            "directory_profile"),
    SourceTypeRule(re.compile(r"zoominfo\.com/"),                 "directory_profile"),
    SourceTypeRule(re.compile(r"about\.me/"),                     "directory_profile"),
    SourceTypeRule(re.compile(r"gravatar\.com/"),                 "directory_profile"),

    # Company / organisation pages — broad match, refined by source collector
    SourceTypeRule(re.compile(r"/team|/about|/people|/leadership"), "company_page"),

    # Conference & university pages — must come before generic /staff so academic
    # domains using /staff are classified correctly.
    SourceTypeRule(re.compile(r"\.edu/(?:faculty|research|staff|profile|people)"), "conference_or_university"),
    SourceTypeRule(re.compile(r"\.ac\.[a-z]{2}/(?:faculty|research|staff|profile|people)"), "conference_or_university"),
    SourceTypeRule(re.compile(r"(?:conference|proceedings|symposium|workshop)\.[a-z]+/"), "conference_or_university"),
    SourceTypeRule(re.compile(r"/(?:speaker|presenter|author)s?/[^/]{3,}"), "conference_or_university"),

    # Generic /staff for non-academic sites
    SourceTypeRule(re.compile(r"/staff/"), "company_page"),

    # Press — broad; collector will check robots.txt
    SourceTypeRule(re.compile(r"techcrunch|wired\.com|bloomberg\.com|reuters|nation\.co\.ke|businessdailyafrica|standardmedia|theeastafrican\.co\.ke|capital(?:fm|business)\.co\.ke"), "press"),
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
        import asyncio
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

        def _do_search() -> list[dict]:
            try:
                results = []
                with DDGS_cls(timeout=4) as ddgs:
                    for r in ddgs.text(query, max_results=limit):
                        results.append({
                            "url": r.get("href", ""),
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                        })
                return results
            except Exception as exc:
                logger.warning("discovery.ddgs_search_failed", query=query[:40], error=str(exc))
                return []

        try:
            results = await asyncio.wait_for(asyncio.to_thread(_do_search), timeout=5.0)
            logger.info("discovery.ddgs_results", query=query[:60], count=len(results))
            return results
        except Exception as exc:
            logger.warning("discovery.ddgs_timeout", query=query[:60], error=str(exc))
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
        async with httpx.AsyncClient(timeout=8) as client:
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
    Build a focused list of search queries from the QueryContext.
    Capped at top 3 high-yield queries to prevent provider throttling.
    """
    queries: list[str] = []
    hints = context.hints
    base_name = context.canonical_name

    # 1. Primary contextual query
    q1 = f'"{base_name}"'
    if hints.get("organization"):
        q1 += f' "{hints["organization"]}"'
    if hints.get("role"):
        q1 += f' "{hints["role"]}"'
    elif hints.get("country"):
        q1 += f' {hints["country"]}'
    queries.append(q1)

    # 2. Key professional registries
    queries.append(f'site:linkedin.com/in/ "{base_name}"')
    queries.append(f'site:github.com "{base_name}"')

    # Deduplicate while preserving order, cap at 3
    return list(dict.fromkeys(queries))[:3]


async def discover_candidates(
    context: QueryContext,
    provider: SearchProvider,
    max_candidates: int = 10,
) -> list[CandidateURL]:
    """
    Run discovery queries concurrently and return allowlisted candidate URLs.
    """
    import asyncio
    queries = _build_queries(context)
    raw_results: list[dict] = []

    # Run queries concurrently in parallel
    search_tasks = [provider.search(q, limit=8) for q in queries]
    batch_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    for i, res in enumerate(batch_results):
        if isinstance(res, list):
            for r in res:
                r["_query_index"] = i
            raw_results.extend(res)
        elif isinstance(res, Exception):
            logger.warning("discovery.batch_query_failed", query=queries[i], error=str(res))

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
