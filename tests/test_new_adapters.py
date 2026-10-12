"""
Tests for V2 source adapter scaffolds: University/Registry, Patents, Conference.

All HTTP calls are mocked (respx) so tests run offline without real API calls.
Each test class covers one adapter. Tests verify:
  - CollectedSource is returned with correct fields when data is found.
  - None is returned when no results are available.
  - Rendered text contains the expected person name and result data.
  - Claim-relevant fields (organization, role, publication) appear in rendered text.

TODO (lameckkipsang — Tasks 1 & 2):
  Fill in every ``# TODO`` block below once you implement the corresponding
  adapter function. The test class skeletons match the function signatures in
  university_adapter.py and patents_adapter.py.

TODO (you — Task 3):
  Fill in the ConferenceAdapterTests class once conference_adapter.py is implemented.

Run with:
  source ~/workenv/bin/activate
  pytest tests/test_new_adapters.py -v
"""

import json
import time

import pytest
import respx
import httpx

from app.core.adapters.university_adapter import (
    fetch_university_and_registry,
    _render_text as university_render_text,
)
from app.core.adapters.patents_adapter import (
    fetch_patents,
    _render_text as patents_render_text,
)
from app.core.adapters.conference_adapter import (
    fetch_conference_papers,
    _deduplicate,
    _extract_profile_urls,
)
from app.core.collector import CollectedSource


# ─────────────────────────────────────────────────────────────────────────────
# University / Registry adapter tests  (Tasks 1 — lameckkipsang)
# ─────────────────────────────────────────────────────────────────────────────

class TestUniversityAdapter:
    """Tests for fetch_university_and_registry."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_results(self):
        """Should return None when all sources return empty results."""
        # No mocks needed — _fetch_* helpers return [] by default (scaffold stubs).
        result = await fetch_university_and_registry("Nonexistent Person XYZ")
        # Until implemented, stubs return [] → _render_text returns "" → None.
        assert result is None

    @pytest.mark.asyncio
    async def test_collected_source_fields(self):
        """
        When results are found, CollectedSource must have:
          - url (non-empty string)
          - domain (non-empty string)
          - source_type == "university_page"
          - title containing the person's name
          - text containing the person's name
          - retrieved_at set (> 0)
          - status_code == 200

        TODO (lameckkipsang):
          1. Mock the HTTP responses for at least one university search URL
             using respx so the adapter returns real results.
          2. Assert all fields above.
        """
        pytest.skip("TODO: implement after _fetch_university_results is done")

    @pytest.mark.asyncio
    async def test_organization_hint_filters_results(self):
        """
        When organization_hint is provided, results from other orgs should be
        deprioritised (the matching org's result appears in the text).

        TODO (lameckkipsang):
          Mock two university results — one from "University of Nairobi", one from
          "Strathmore University". Call with organization_hint="Nairobi".
          Assert "University of Nairobi" appears before "Strathmore" in the text.
        """
        pytest.skip("TODO: implement after organization_hint filtering is done")

    @pytest.mark.asyncio
    async def test_registry_result_in_text(self):
        """
        A KMPDC / LSK registry result should appear in the rendered text.

        TODO (lameckkipsang):
          Mock the KMPDC search endpoint to return a result with name, registry,
          and registration number. Assert the rendered text contains:
            - The person's name
            - "KMPDC" or "registered" keyword
            - The registration number
        """
        pytest.skip("TODO: implement after _fetch_registry_results is done")

    @pytest.mark.asyncio
    async def test_no_out_of_scope_data_in_text(self):
        """
        The rendered text must NOT contain home addresses, phone numbers,
        personal email, or any biometric data.

        TODO (lameckkipsang):
          Mock a result that contains an address field in the source HTML.
          Assert the rendered text does not include that address.
        """
        pytest.skip("TODO: implement after _render_text handles this")

    # ── Unit tests for _render_text ───────────────────────────────────────────

    def test_render_text_empty(self):
        """_render_text returns empty string when both lists are empty."""
        assert university_render_text("Alice", [], []) == ""

    def test_render_text_contains_name(self):
        """
        TODO (lameckkipsang):
          Call _render_text with at least one non-empty result dict.
          Assert the returned string contains the person's name.
        """
        pytest.skip("TODO: implement after _render_text is done")

    def test_render_text_contains_org(self):
        """
        TODO (lameckkipsang):
          Call _render_text with a university result that has an org field.
          Assert the rendered text contains that org name.
        """
        pytest.skip("TODO: implement after _render_text is done")

    def test_render_text_registry_includes_registration_number(self):
        """
        TODO (lameckkipsang):
          Call _render_text with a registry result that has a registration_number.
          Assert the rendered text contains that number.
        """
        pytest.skip("TODO: implement after _render_text is done")


# ─────────────────────────────────────────────────────────────────────────────
# Patents adapter tests  (Task 2 — lameckkipsang)
# ─────────────────────────────────────────────────────────────────────────────

class TestPatentsAdapter:
    """Tests for fetch_patents."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_results(self):
        """Should return None when all patent sources return empty results."""
        result = await fetch_patents("Nonexistent Inventor XYZ")
        assert result is None

    @pytest.mark.asyncio
    async def test_collected_source_fields(self):
        """
        When patents are found, CollectedSource must have:
          - url (non-empty)
          - domain (non-empty)
          - source_type == "patent"
          - title containing the person's name
          - text with "inventor" keyword
          - retrieved_at > 0
          - status_code == 200

        TODO (lameckkipsang):
          Mock the WIPO PatentScope API to return a sample patent result.
          Assert all the fields above.
        """
        pytest.skip("TODO: implement after _fetch_wipo_patents is done")

    @pytest.mark.asyncio
    async def test_wipo_result_in_text(self):
        """
        A WIPO patent result should appear in rendered text with title and year.

        TODO (lameckkipsang):
          Mock WIPO_SEARCH_URL with a JSON payload containing one patent:
            title="Smart Water Meter KE", publication_date="2023-05-01",
            inventor=["John Mwangi"], patent_number="WO2023/123456".
          Call fetch_patents("John Mwangi") and assert the text contains
          "Smart Water Meter KE" and "2023" and "WO2023/123456".
        """
        pytest.skip("TODO: implement after _fetch_wipo_patents is done")

    @pytest.mark.asyncio
    async def test_deduplication_by_patent_number(self):
        """
        The same patent returned by WIPO and Google Patents should appear once.

        TODO (lameckkipsang):
          Mock both WIPO and Google Patents to return a patent with the same
          patent_number. Assert the rendered text lists that patent only once.
        """
        pytest.skip("TODO: implement after deduplication is done")

    @pytest.mark.asyncio
    async def test_no_personal_data_in_text(self):
        """
        Patent results must not include home addresses or personal contact info.

        TODO (lameckkipsang):
          Include an address field in your mock patent response. Assert the
          rendered text does not contain that address string.
        """
        pytest.skip("TODO: implement after _render_text is done")

    # ── Unit tests for _render_text ───────────────────────────────────────────

    def test_render_text_empty(self):
        """_render_text returns empty string for empty patent list."""
        assert patents_render_text("Bob", []) == ""

    def test_render_text_contains_inventor_name(self):
        """
        TODO (lameckkipsang):
          Build a sample patent dict and call patents_render_text.
          Assert the returned string contains "Bob" (the inventor name).
        """
        pytest.skip("TODO: implement after _render_text is done")

    def test_render_text_contains_patent_title(self):
        """
        TODO (lameckkipsang):
          Assert the rendered text contains the patent title string.
        """
        pytest.skip("TODO: implement after _render_text is done")


# ─────────────────────────────────────────────────────────────────────────────
# Conference adapter tests  (Task 3 — you)
# ─────────────────────────────────────────────────────────────────────────────

class TestConferenceAdapter:
    """Tests for fetch_conference_papers."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_results(self):
        """Should return None when ACM, IEEE, and DBLP all return empty results."""
        result = await fetch_conference_papers("Nonexistent Speaker XYZ")
        assert result is None

    @pytest.mark.asyncio
    async def test_collected_source_fields(self):
        """
        TODO (you):
          Mock at least one of ACM / IEEE / DBLP to return a sample paper.
          Assert CollectedSource fields:
            source_type == "conference_paper", text not empty, status_code == 200.
        """
        pytest.skip("TODO: implement after fetch_conference_papers is done")

    @pytest.mark.asyncio
    async def test_dblp_result_in_text(self):
        """
        TODO (you):
          Mock DBLP_AUTHOR_URL and a DBLP author publications response.
          Assert the rendered text contains the paper title and venue.
        """
        pytest.skip("TODO: implement after _fetch_dblp_results is done")

    @pytest.mark.asyncio
    async def test_cross_link_profile_urls_in_text(self):
        """
        When a conference result includes profile_urls (GitHub, ORCID, etc.),
        those URLs must appear in the rendered text so the LLM extraction
        produces profile_url claims used by the cross-link entity resolution signal.

        TODO (you):
          Build a mock result dict with ``profile_urls=["https://github.com/drwanjiku"]``.
          Call _render_text and assert the GitHub URL appears in the output.
        """
        pytest.skip("TODO: implement after _render_text includes profile_urls")

    # ── Unit tests for helpers ────────────────────────────────────────────────

    def test_deduplicate_by_doi(self):
        """Results with the same DOI should be collapsed to one entry."""
        r1 = {"title": "ML in Africa", "doi": "10.1145/12345", "year": "2023"}
        r2 = {"title": "ML in Africa", "doi": "10.1145/12345", "year": "2023"}
        r3 = {"title": "Another Paper", "doi": "10.1145/99999", "year": "2022"}
        result = _deduplicate([r1, r2, r3])
        assert len(result) == 2

    def test_deduplicate_by_title_when_no_doi(self):
        """Results with identical normalised titles and no DOI should be collapsed."""
        r1 = {"title": "Nairobi Smart City", "doi": "", "year": "2022"}
        r2 = {"title": "Nairobi Smart City", "doi": "", "year": "2022"}
        result = _deduplicate([r1, r2])
        assert len(result) == 1

    def test_deduplicate_preserves_unique_entries(self):
        """Different papers should not be collapsed."""
        r1 = {"title": "Paper A", "doi": "10.1145/111"}
        r2 = {"title": "Paper B", "doi": "10.1145/222"}
        assert len(_deduplicate([r1, r2])) == 2

    def test_extract_profile_urls_github(self):
        """
        TODO (you):
          Build a result dict with profile_urls containing a GitHub URL.
          Assert _extract_profile_urls returns that URL.
        """
        pytest.skip("TODO: implement after _extract_profile_urls is done")

    def test_extract_profile_urls_ignores_noise(self):
        """
        TODO (you):
          Build a result dict with profile_urls mixing a GitHub URL and a
          random non-profile URL (e.g. 'https://example.com/foo').
          Assert only the GitHub URL is returned.
        """
        pytest.skip("TODO: implement after _extract_profile_urls filter is done")
