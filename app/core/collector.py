"""
Source Collector module.

Fetches a URL and returns clean, readable text. Responsibilities:
  1. robots.txt compliance — never fetch a disallowed path.
  2. Per-domain rate limiting — honour configured delay between requests
     to the same domain to avoid hammering sources.
  3. Retries with exponential back-off for transient errors.
  4. Text extraction — strips HTML tags and returns readable plain text.
  5. Content size limits — cap text to avoid extremely large pages.
  6. Domain allowlist guard — refuses to fetch domains that are not
     in the approved source-type registry (defence in depth).

What we do NOT store: full HTML, cookies, sessions, user data.
We keep: extracted plain text (ephemeral, not persisted) + metadata.
"""

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.core.discovery import classify_url

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
USER_AGENT = "PersonSearchBot/1.0 (+https://github.com/personsearch; research only)"
MAX_CONTENT_BYTES = 512_000       # 512 KB cap on raw HTML
MAX_TEXT_CHARS = 20_000           # cap on extracted plain text sent to LLM
ROBOTS_CACHE_TTL = 3600           # seconds to cache robots.txt decisions
REQUEST_TIMEOUT = settings.collector_timeout_seconds
MAX_RETRIES = settings.collector_max_retries
DOMAIN_DELAY = settings.collector_per_domain_delay_seconds


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class CollectedSource:
    url: str
    domain: str
    source_type: str
    title: str
    text: str                      # clean plain text, capped at MAX_TEXT_CHARS
    retrieved_at: float = field(default_factory=time.time)
    status_code: int = 200
    content_hash: str = ""         # SHA-256 of text — for staleness detection

    def __post_init__(self) -> None:
        if self.text and not self.content_hash:
            self.content_hash = hashlib.sha256(self.text.encode()).hexdigest()


# ── Robots.txt cache ───────────────────────────────────────────────────────────

class RobotsCache:
    """
    In-memory cache of robots.txt decisions.

    Each entry has a TTL; expired entries are re-fetched.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[RobotFileParser, float]] = {}

    async def is_allowed(self, url: str, client: httpx.AsyncClient) -> bool:
        domain = _domain(url)
        robots_url = f"https://{domain}/robots.txt"
        now = time.time()

        parser, expires = self._cache.get(domain, (None, 0.0))
        if parser is None or now > expires:
            parser = await self._fetch_robots(robots_url, client)
            self._cache[domain] = (parser, now + ROBOTS_CACHE_TTL)

        allowed = parser.can_fetch(USER_AGENT, url)
        if not allowed:
            logger.warning("collector.robots_disallowed", url=url)
        return allowed

    @staticmethod
    async def _fetch_robots(
        robots_url: str, client: httpx.AsyncClient
    ) -> RobotFileParser:
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            resp = await client.get(robots_url, timeout=5)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            # Non-200 → treat as "allow all" per convention
        except Exception as exc:
            logger.debug("collector.robots_fetch_failed", url=robots_url, error=str(exc))
        return parser


# ── Per-domain throttle ────────────────────────────────────────────────────────

class DomainThrottle:
    """Tracks the last request time per domain and enforces a minimum delay."""

    def __init__(self, delay: float = DOMAIN_DELAY) -> None:
        self._last: dict[str, float] = {}
        self._delay = delay

    async def wait(self, domain: str) -> None:
        last = self._last.get(domain, 0.0)
        wait_for = self._delay - (time.time() - last)
        if wait_for > 0:
            logger.debug("collector.throttle", domain=domain, wait_s=round(wait_for, 2))
            await asyncio.sleep(wait_for)
        self._last[domain] = time.time()


# ── Text extraction ────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _html_to_text(html: str) -> str:
    """Strip HTML tags and return clean, whitespace-normalised plain text."""
    html = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", html)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()[:MAX_TEXT_CHARS]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().lstrip("www.")


# ── Core fetch function ────────────────────────────────────────────────────────

# Module-level shared state (reset per-worker in production)
_robots_cache = RobotsCache()
_domain_throttle = DomainThrottle()


async def _fetch_raw(url: str, client: httpx.AsyncClient) -> tuple[str, int]:
    """
    Fetch a URL and return (html_text, status_code).

    Raises httpx.HTTPError on non-2xx so tenacity can retry.
    """
    resp = await client.get(
        url,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    resp.raise_for_status()
    # Cap raw content to avoid giant pages
    raw = resp.text[:MAX_CONTENT_BYTES]
    return raw, resp.status_code


async def collect_source(
    url: str,
    *,
    robots_cache: RobotsCache | None = None,
    throttle: DomainThrottle | None = None,
) -> CollectedSource | None:
    """
    Fetch a single URL and return a CollectedSource, or None if:
      - the URL is not on the source-type allowlist
      - robots.txt disallows our bot
      - the request fails after all retries

    Args:
        url: The URL to fetch.
        robots_cache: Optional shared RobotsCache (uses module-level default).
        throttle: Optional shared DomainThrottle (uses module-level default).

    The function never raises — failures are logged and None is returned
    so a single bad source never halts the pipeline.
    """
    rc = robots_cache or _robots_cache
    th = throttle or _domain_throttle
    domain = _domain(url)

    log = logger.bind(url=url, domain=domain)

    # ── 1. Source-type allowlist check ─────────────────────────────────────────
    source_type = classify_url(url)
    if source_type is None:
        log.warning("collector.url_not_allowlisted")
        return None

    async with httpx.AsyncClient(verify=True) as client:
        # ── 2. robots.txt compliance ───────────────────────────────────────────
        if not await rc.is_allowed(url, client):
            return None

        # ── 3. Per-domain throttle ─────────────────────────────────────────────
        await th.wait(domain)

        # ── 4. Fetch with retries ──────────────────────────────────────────────
        try:
            html, status_code = await _fetch_with_retry(url, client)
        except Exception as exc:
            log.error("collector.fetch_failed", error=str(exc))
            return None

    # ── 5. Extract text and title ──────────────────────────────────────────────
    title = _extract_title(html)
    text = _html_to_text(html)

    log.info(
        "collector.collected",
        source_type=source_type,
        title=title[:80],
        text_chars=len(text),
    )

    return CollectedSource(
        url=url,
        domain=domain,
        source_type=source_type,
        title=title,
        text=text,
        status_code=status_code,
    )


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(MAX_RETRIES),
    reraise=True,
)
async def _fetch_with_retry(url: str, client: httpx.AsyncClient) -> tuple[str, int]:
    """Thin wrapper so tenacity only retries transient network errors."""
    return await _fetch_raw(url, client)


# ── Batch collector ────────────────────────────────────────────────────────────

async def collect_sources(
    urls: list[tuple[str, str]],  # (url, source_type_hint)
    max_concurrent: int = 5,
) -> list[CollectedSource]:
    """
    Collect multiple sources concurrently with a semaphore cap.

    Args:
        urls: List of (url, source_type_hint) tuples from the discovery stage.
        max_concurrent: Maximum simultaneous in-flight requests.

    Returns:
        List of successfully collected sources (None results are filtered out).
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _guarded(url: str) -> CollectedSource | None:
        async with semaphore:
            return await collect_source(url)

    tasks = [_guarded(url) for url, _ in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    collected = []
    for r in results:
        if isinstance(r, Exception):
            logger.error("collector.batch_error", error=str(r))
        elif r is not None:
            collected.append(r)

    logger.info(
        "collector.batch_done",
        total=len(urls),
        collected=len(collected),
        failed=len(urls) - len(collected),
    )
    return collected
