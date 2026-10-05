"""
Tests for strict hint enforcement (Country code, organization, role, and sector).

Verifies that when the user provides hints (e.g. country="KE" or organization="Safaricom"):
  1. Discovery queries strictly incorporate country names and organization hints.
  2. Candidates with conflicting countries (e.g. US, UK, Australia, UAE) are dropped during discovery.
  3. In entity resolution, clusters from conflicting countries or organizations are vetoed from primaries.
  4. The primary result is solely the person matching the country and contextual hints.
"""

import pytest

from app.core.country_utils import (
    parse_country,
    text_matches_country,
    text_conflicts_with_country,
)
from app.core.discovery import _build_queries, discover_candidates, SearchProvider
from app.core.entity_resolution import resolve_entities, PersonCluster
from app.core.query_understanding import QueryContext
from app.schemas.search import SearchHints


class TestCountryUtils:
    def test_parse_country_code(self):
        c = parse_country("KE")
        assert c is not None
        assert c.code == "KE"
        assert c.name == "Kenya"
        assert c.demonym == "Kenyan"

    def test_parse_country_name(self):
        c = parse_country("kenya")
        assert c is not None
        assert c.code == "KE"

        us = parse_country("United States")
        assert us is not None
        assert us.code == "US"

    def test_matches_country(self):
        ke = parse_country("KE")
        assert text_matches_country("Senior Advisor at Safaricom PLC in Nairobi, Kenya", ke)
        assert text_matches_country("https://ke.linkedin.com/in/john-kamau", ke)
        assert text_matches_country("Profile in Nairobi County", ke)
        assert not text_matches_country("Software Engineer in London, England", ke)

    def test_conflicts_with_country(self):
        ke = parse_country("KE")
        # Text clearly pointing to US
        is_conf, other = text_conflicts_with_country(
            "John Kamau - Location: United States | Professional Profile | LinkedIn", ke
        )
        assert is_conf is True
        assert other == "United States"

        # Text with UK LinkedIn subdomain
        is_conf, other = text_conflicts_with_country(
            "https://uk.linkedin.com/in/john-kamau - London, UK", ke
        )
        assert is_conf is True
        assert other == "United Kingdom"

        # Text in Kenya does not conflict with KE
        is_conf, _ = text_conflicts_with_country(
            "https://ke.linkedin.com/in/john-kamau - Nairobi, Kenya", ke
        )
        assert is_conf is False


class TestDiscoveryHintEnforcement:
    def test_build_queries_with_country_code_expands_to_name(self):
        ctx = QueryContext(
            canonical_name="John Kamau",
            name_variants=[],
            hints={"country": "KE"},
        )
        queries = _build_queries(ctx)
        assert len(queries) >= 2
        # All queries should incorporate Kenya
        assert any("Kenya" in q for q in queries)
        assert any("site:linkedin.com/in/" in q and "Kenya" in q for q in queries)
        # Should not generate bare worldwide linkedin query
        assert 'site:linkedin.com/in/ "John Kamau"' not in queries

    def test_build_queries_with_country_and_organization(self):
        ctx = QueryContext(
            canonical_name="John Kamau",
            name_variants=[],
            hints={"country": "KE", "organization": "Safaricom"},
        )
        queries = _build_queries(ctx)
        # Primary query combines both
        assert any("Safaricom" in q and "Kenya" in q for q in queries)
        assert any("site:linkedin.com/in/" in q and "Safaricom" in q for q in queries)

    @pytest.mark.asyncio
    async def test_discover_candidates_drops_conflicting_countries(self):
        class MockProvider(SearchProvider):
            async def search(self, query: str, limit: int = 10) -> list[dict]:
                return [
                    {
                        "url": "https://ke.linkedin.com/in/john-kamau-ke",
                        "title": "John Kamau - Safaricom PLC | Nairobi, Kenya",
                        "snippet": "Software Engineer at Safaricom PLC in Nairobi, Kenya",
                    },
                    {
                        "url": "https://www.linkedin.com/in/john-kamau-us",
                        "title": "John Kamau - United States | Professional Profile | LinkedIn",
                        "snippet": "Location: United States. Experience: Go Solar Systems Ltd.",
                    },
                    {
                        "url": "https://ae.linkedin.com/in/john-kamau-uae",
                        "title": "John Kamau - Supply Chain Leader | Dubai UAE",
                        "snippet": "Location: Dubai, United Arab Emirates.",
                    },
                ]

        ctx = QueryContext(
            canonical_name="John Kamau",
            name_variants=[],
            hints={"country": "KE", "organization": "Safaricom"},
        )
        candidates = await discover_candidates(ctx, MockProvider(), max_candidates=10)
        urls = [c.url for c in candidates]

        # The Kenya candidate must be included and ranked first
        assert "https://ke.linkedin.com/in/john-kamau-ke" in urls
        assert candidates[0].url == "https://ke.linkedin.com/in/john-kamau-ke"

        # Candidates from US and UAE must be completely dropped!
        assert "https://www.linkedin.com/in/john-kamau-us" not in urls
        assert "https://ae.linkedin.com/in/john-kamau-uae" not in urls


class TestEntityResolutionHintEnforcement:
    def test_conflicting_country_vetoed_from_primaries(self):
        candidates = [
            {
                "url": "https://ke.linkedin.com/in/john-kamau-ke",
                "name_on_source": "John Kamau",
                "claims": [
                    {"claim_type": "organization", "value": "Safaricom PLC", "evidence_span": "Safaricom PLC in Nairobi, Kenya"},
                    {"claim_type": "occupation", "value": "Software Engineer", "evidence_span": "Software Engineer in Kenya"},
                ],
            },
            {
                "url": "https://www.linkedin.com/in/john-kamau-us",
                "name_on_source": "John Kamau",
                "claims": [
                    {"claim_type": "organization", "value": "Go Solar Systems", "evidence_span": "Go Solar Systems in Location: United States"},
                    {"claim_type": "occupation", "value": "Operations Manager", "evidence_span": "Operations Manager in United States"},
                ],
            },
        ]

        hints = SearchHints(country="KE", organization="Safaricom")
        primaries, alternatives = resolve_entities(
            candidate_claim_sets=candidates,
            target_name="John Kamau",
            hints=hints,
        )

        # Primary cluster must ONLY contain the Kenyan candidate matching Safaricom
        assert len(primaries) == 1
        assert "https://ke.linkedin.com/in/john-kamau-ke" in primaries[0].source_urls

        # The US candidate must be relegated to alternatives
        assert len(alternatives) == 1
        assert "https://www.linkedin.com/in/john-kamau-us" in alternatives[0].source_urls
        assert alternatives[0].signals.get("country_conflict") is True

    def test_conflicting_organization_vetoed_from_primaries(self):
        candidates = [
            {
                "url": "https://safaricom.co.ke/team/jkamau",
                "name_on_source": "John Kamau",
                "claims": [
                    {"claim_type": "organization", "value": "Safaricom PLC", "evidence_span": "Safaricom PLC"},
                    {"claim_type": "occupation", "value": "Software Engineer", "evidence_span": "Software Engineer"},
                ],
            },
            {
                "url": "https://knh.or.ke/staff/jkamau",
                "name_on_source": "John Kamau",
                "claims": [
                    {"claim_type": "organization", "value": "Kenyatta National Hospital", "evidence_span": "Kenyatta National Hospital"},
                    {"claim_type": "occupation", "value": "Pediatric Surgeon", "evidence_span": "Pediatric Surgeon"},
                ],
            },
        ]

        # Hint explicitly specifies Safaricom
        hints = SearchHints(organization="Safaricom")
        primaries, alternatives = resolve_entities(
            candidate_claim_sets=candidates,
            target_name="John Kamau",
            hints=hints,
        )

        # Safaricom cluster must be primary, KNH cluster must be alternative
        assert len(primaries) == 1
        assert "https://safaricom.co.ke/team/jkamau" in primaries[0].source_urls
        assert len(alternatives) == 1
        assert "https://knh.or.ke/staff/jkamau" in alternatives[0].source_urls
