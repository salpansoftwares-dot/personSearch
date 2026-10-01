"""
Tests for Discovery and Collector modules.

These tests use mocks/stubs wherever possible so they run offline.
Tests marked with @pytest.mark.live are skipped unless RUN_LIVE_TESTS=1.
"""

import asyncio
import os
import time
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


# ── Discovery tests ────────────────────────────────────────────────────────────

class TestClassifyUrl:
    def test_linkedin_profile(self):
        from app.core.discovery import classify_url
        assert classify_url("https://www.linkedin.com/in/john-kamau") == "linkedin_profile"

    def test_github_profile(self):
        from app.core.discovery import classify_url
        assert classify_url("https://github.com/johnkamau") == "github_profile"

    def test_out_of_scope_url_returns_none(self):
        from app.core.discovery import classify_url
        # Facebook personal profile is NOT on the allowlist
        assert classify_url("https://www.facebook.com/john.kamau") is None

    def test_orcid_profile(self):
        from app.core.discovery import classify_url
        assert classify_url("https://orcid.org/0000-0002-1234-5678") == "orcid_profile"

    def test_company_page(self):
        from app.core.discovery import classify_url
        assert classify_url("https://acme.com/team/john") == "company_page"


class TestBuildQueries:
    def test_includes_canonical_name(self):
        from app.core.discovery import _build_queries
        from app.core.query_understanding import QueryContext
        ctx = QueryContext(
            canonical_name="John Kamau",
            name_variants=[],
            hints={"organization": "Acme Ltd"},
        )
        queries = _build_queries(ctx)
        assert any("John Kamau" in q for q in queries)

    def test_includes_organization_hint(self):
        from app.core.discovery import _build_queries
        from app.core.query_understanding import QueryContext
        ctx = QueryContext(
            canonical_name="Jane Doe",
            name_variants=[],
            hints={"organization": "BigCorp"},
        )
        queries = _build_queries(ctx)
        assert any("BigCorp" in q for q in queries)

    def test_includes_targeted_linkedin_query(self):
        from app.core.discovery import _build_queries
        from app.core.query_understanding import QueryContext
        ctx = QueryContext(canonical_name="Jane Doe", name_variants=[], hints={})
        queries = _build_queries(ctx)
        assert any("site:linkedin.com" in q for q in queries)

    def test_no_duplicate_queries(self):
        from app.core.discovery import _build_queries
        from app.core.query_understanding import QueryContext
        ctx = QueryContext(canonical_name="John Kamau", name_variants=[], hints={})
        queries = _build_queries(ctx)
        assert len(queries) == len(set(queries))


class TestDiscoverCandidates:
    @pytest.mark.asyncio
    async def test_filters_out_non_allowlisted_urls(self):
        from app.core.discovery import discover_candidates, SearchProvider
        from app.core.query_understanding import QueryContext

        class FakeProvider(SearchProvider):
            async def search(self, query, limit=10):
                return [
                    {"url": "https://linkedin.com/in/john-kamau", "title": "John Kamau", "snippet": ""},
                    {"url": "https://facebook.com/john.kamau", "title": "John Kamau FB", "snippet": ""},
                ]

        ctx = QueryContext(canonical_name="John Kamau", name_variants=[], hints={})
        results = await discover_candidates(ctx, FakeProvider(), max_candidates=20)
        urls = [r.url for r in results]
        assert "https://linkedin.com/in/john-kamau" in urls
        assert "https://facebook.com/john.kamau" not in urls

    @pytest.mark.asyncio
    async def test_deduplicates_results(self):
        from app.core.discovery import discover_candidates, SearchProvider
        from app.core.query_understanding import QueryContext

        class DuplicateProvider(SearchProvider):
            async def search(self, query, limit=10):
                return [
                    {"url": "https://linkedin.com/in/john-kamau", "title": "John", "snippet": ""},
                    {"url": "https://linkedin.com/in/john-kamau", "title": "John", "snippet": ""},
                ]

        ctx = QueryContext(canonical_name="John Kamau", name_variants=[], hints={})
        results = await discover_candidates(ctx, DuplicateProvider())
        assert len([r for r in results if r.url == "https://linkedin.com/in/john-kamau"]) == 1


# ── Collector tests ────────────────────────────────────────────────────────────

class TestHtmlToText:
    def test_strips_html_tags(self):
        from app.core.collector import _html_to_text
        html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        assert "<" not in _html_to_text(html)
        assert "Hello" in _html_to_text(html)

    def test_removes_script_blocks(self):
        from app.core.collector import _html_to_text
        html = "<body><script>alert('xss')</script><p>Content</p></body>"
        text = _html_to_text(html)
        assert "alert" not in text
        assert "Content" in text

    def test_normalises_whitespace(self):
        from app.core.collector import _html_to_text
        html = "<p>Hello   \n\n   World</p>"
        text = _html_to_text(html)
        assert "  " not in text  # no double spaces


class TestDomainThrottle:
    @pytest.mark.asyncio
    async def test_enforces_delay(self):
        from app.core.collector import DomainThrottle
        throttle = DomainThrottle(delay=0.1)
        await throttle.wait("example.com")
        t0 = time.time()
        await throttle.wait("example.com")
        elapsed = time.time() - t0
        assert elapsed >= 0.09, f"Expected ≥0.09s delay, got {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_different_domains_not_throttled(self):
        from app.core.collector import DomainThrottle
        throttle = DomainThrottle(delay=1.0)
        await throttle.wait("a.com")
        t0 = time.time()
        await throttle.wait("b.com")  # different domain — no delay
        elapsed = time.time() - t0
        assert elapsed < 0.5


class TestCollectSource:
    @pytest.mark.asyncio
    async def test_rejects_non_allowlisted_url(self):
        from app.core.collector import collect_source
        result = await collect_source("https://facebook.com/john.kamau")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_robots_disallow(self):
        from app.core.collector import collect_source, RobotsCache, DomainThrottle

        class DisallowAll(RobotsCache):
            async def is_allowed(self, url, client):
                return False

        result = await collect_source(
            "https://github.com/johndoe",
            robots_cache=DisallowAll(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_fetch_failure(self):
        from app.core.collector import collect_source, RobotsCache, DomainThrottle

        class AllowAll(RobotsCache):
            async def is_allowed(self, url, client):
                return True

        class NoDelay(DomainThrottle):
            async def wait(self, domain):
                pass

        with patch("app.core.collector._fetch_with_retry", side_effect=Exception("timeout")):
            result = await collect_source(
                "https://github.com/johndoe",
                robots_cache=AllowAll(),
                throttle=NoDelay(),
            )
        assert result is None
