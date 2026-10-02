"""
Tests for V2 source adapters: ORCID, Semantic Scholar, PubMed.

All HTTP calls are mocked so these tests run offline without API keys.
"""

import json
import pytest
import respx
import httpx

from app.core.adapters.orcid_adapter import (
    fetch_orcid_profile,
    find_orcid_ids_for_name,
    _render_text as orcid_render,
    _extract_name,
    _extract_employments,
    _extract_educations,
    _extract_works,
)
from app.core.adapters.semantic_scholar_adapter import fetch_semantic_scholar_author
from app.core.adapters.pubmed_adapter import (
    fetch_pubmed_author,
    _parse_pubmed_xml,
    _render_text as pubmed_render,
)
from app.core.collector import CollectedSource


# ─────────────────────────────────────────────────────────────────────────────
# ORCID adapter tests
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_ORCID_RECORD = {
    "orcid-identifier": {"path": "0000-0002-1825-0097"},
    "person": {
        "name": {
            "given-names": {"value": "Jane"},
            "family-name": {"value": "Researcher"},
        },
        "biography": {"content": "Professor of Computer Science at University of Nairobi."},
    },
    "activities-summary": {
        "employments": {
            "affiliation-group": [
                {
                    "summaries": [
                        {
                            "employment-summary": {
                                "organization": {"name": "University of Nairobi"},
                                "role-title": "Professor",
                                "start-date": {"year": {"value": "2018"}},
                                "end-date": None,
                            }
                        }
                    ]
                }
            ]
        },
        "educations": {
            "affiliation-group": [
                {
                    "summaries": [
                        {
                            "education-summary": {
                                "organization": {"name": "MIT"},
                                "role-title": "PhD Computer Science",
                            }
                        }
                    ]
                }
            ]
        },
        "works": {
            "group": [
                {
                    "work-summary": [
                        {
                            "title": {"title": {"value": "Deep Learning for African Languages"}},
                            "type": "journal-article",
                        }
                    ]
                }
            ]
        },
    },
}

SAMPLE_ORCID_SEARCH = {
    "result": [
        {
            "orcid-identifier": {"path": "0000-0002-1825-0097"}
        }
    ]
}


def test_orcid_extract_name():
    name = _extract_name(SAMPLE_ORCID_RECORD)
    assert name == "Jane Researcher"


def test_orcid_extract_employments():
    emps = _extract_employments(SAMPLE_ORCID_RECORD)
    assert len(emps) == 1
    assert emps[0]["organization"] == "University of Nairobi"
    assert emps[0]["role"] == "Professor"
    assert emps[0]["start"] == "2018"


def test_orcid_extract_educations():
    edus = _extract_educations(SAMPLE_ORCID_RECORD)
    assert len(edus) == 1
    assert edus[0]["organization"] == "MIT"
    assert edus[0]["degree"] == "PhD Computer Science"


def test_orcid_extract_works():
    works = _extract_works(SAMPLE_ORCID_RECORD)
    assert len(works) == 1
    assert "Deep Learning for African Languages" in works[0]


def test_orcid_render_text_contains_key_fields():
    text = orcid_render(
        "0000-0002-1825-0097",
        "Jane Researcher",
        "Professor of Computer Science at University of Nairobi.",
        [{"organization": "University of Nairobi", "role": "Professor", "start": "2018", "end": ""}],
        [{"organization": "MIT", "degree": "PhD Computer Science"}],
        ["Deep Learning for African Languages"],
    )
    assert "Jane Researcher" in text
    assert "University of Nairobi" in text
    assert "Professor" in text
    assert "MIT" in text
    assert "Deep Learning for African Languages" in text
    # Should NOT contain HTML or JSON artifacts
    assert "<" not in text
    assert "}" not in text


@pytest.mark.anyio
@respx.mock
async def test_fetch_orcid_profile_success():
    """fetch_orcid_profile returns a CollectedSource for a valid ORCID record."""
    orcid_id = "0000-0002-1825-0097"
    api_url = f"https://pub.orcid.org/v3.0/{orcid_id}"

    respx.get(api_url).mock(
        return_value=httpx.Response(200, json=SAMPLE_ORCID_RECORD)
    )

    result = await fetch_orcid_profile(orcid_id, name_hint="Jane Researcher")

    assert result is not None
    assert isinstance(result, CollectedSource)
    assert result.source_type == "orcid_profile"
    assert result.domain == "orcid.org"
    assert "University of Nairobi" in result.text
    assert "Jane Researcher" in result.text
    assert result.content_hash  # hash is computed


@pytest.mark.anyio
@respx.mock
async def test_fetch_orcid_profile_404():
    """fetch_orcid_profile returns None for a 404 response."""
    orcid_id = "0000-0000-0000-0000"
    api_url = f"https://pub.orcid.org/v3.0/{orcid_id}"

    respx.get(api_url).mock(return_value=httpx.Response(404))

    result = await fetch_orcid_profile(orcid_id)
    assert result is None


@pytest.mark.anyio
@respx.mock
async def test_find_orcid_ids_for_name():
    """find_orcid_ids_for_name returns a list of ORCID iDs from the search API."""
    respx.get("https://pub.orcid.org/v3.0/search").mock(
        return_value=httpx.Response(200, json=SAMPLE_ORCID_SEARCH)
    )

    ids = await find_orcid_ids_for_name("Jane Researcher")
    assert ids == ["0000-0002-1825-0097"]


@pytest.mark.anyio
@respx.mock
async def test_find_orcid_ids_network_error():
    """find_orcid_ids_for_name returns [] on network error."""
    respx.get("https://pub.orcid.org/v3.0/search").mock(
        side_effect=httpx.ConnectError("Network error")
    )

    ids = await find_orcid_ids_for_name("Jane Researcher")
    assert ids == []


# ─────────────────────────────────────────────────────────────────────────────
# Semantic Scholar adapter tests
# ─────────────────────────────────────────────────────────────────────────────

S2_SEARCH_RESPONSE = {
    "data": [
        {
            "authorId": "12345",
            "name": "Jane Researcher",
            "affiliations": ["University of Nairobi"],
            "paperCount": 25,
            "hIndex": 8,
        }
    ]
}

S2_PAPERS_RESPONSE = {
    "data": [
        {
            "title": "Neural Machine Translation for Swahili",
            "year": 2022,
            "venue": "ACL Anthology",
            "authors": [{"name": "Jane Researcher"}, {"name": "Co Author"}],
        },
        {
            "title": "Low-Resource Language Models",
            "year": 2021,
            "venue": "EMNLP",
            "authors": [{"name": "Jane Researcher"}],
        },
    ]
}


@pytest.mark.anyio
@respx.mock
async def test_fetch_semantic_scholar_success():
    """fetch_semantic_scholar_author returns CollectedSources for a known author."""
    respx.get("https://api.semanticscholar.org/graph/v1/author/search").mock(
        return_value=httpx.Response(200, json=S2_SEARCH_RESPONSE)
    )
    respx.get("https://api.semanticscholar.org/graph/v1/author/12345/papers").mock(
        return_value=httpx.Response(200, json=S2_PAPERS_RESPONSE)
    )

    results = await fetch_semantic_scholar_author("Jane Researcher")

    assert len(results) == 1
    src = results[0]
    assert isinstance(src, CollectedSource)
    assert src.source_type == "publication"
    assert "Jane Researcher" in src.text
    assert "University of Nairobi" in src.text
    assert "Neural Machine Translation for Swahili" in src.text


@pytest.mark.anyio
@respx.mock
async def test_fetch_semantic_scholar_no_results():
    """Returns empty list when no authors found."""
    respx.get("https://api.semanticscholar.org/graph/v1/author/search").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    results = await fetch_semantic_scholar_author("Unknown Person XYZ")
    assert results == []


@pytest.mark.anyio
@respx.mock
async def test_fetch_semantic_scholar_with_org_hint():
    """Organization hint filters candidates by affiliation."""
    # Two candidates — only second matches the org hint
    search_response = {
        "data": [
            {
                "authorId": "111",
                "name": "Jane Researcher",
                "affiliations": ["Harvard University"],
                "paperCount": 10,
                "hIndex": 3,
            },
            {
                "authorId": "222",
                "name": "Jane Researcher",
                "affiliations": ["University of Nairobi"],
                "paperCount": 5,
                "hIndex": 2,
            },
        ]
    }
    respx.get("https://api.semanticscholar.org/graph/v1/author/search").mock(
        return_value=httpx.Response(200, json=search_response)
    )
    respx.get("https://api.semanticscholar.org/graph/v1/author/222/papers").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    results = await fetch_semantic_scholar_author(
        "Jane Researcher",
        organization_hint="University of Nairobi",
        max_candidates=1,
    )
    # Should prefer the Nairobi affiliation
    assert len(results) == 1
    assert "222" in results[0].url


# ─────────────────────────────────────────────────────────────────────────────
# PubMed adapter tests
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_PUBMED_ESEARCH = {
    "esearchresult": {
        "count": "2",
        "idlist": ["38000001", "38000002"],
    }
}

SAMPLE_PUBMED_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Machine Learning in Healthcare: A Kenyan Perspective</ArticleTitle>
        <Journal><Title>Journal of Medical Informatics</Title></Journal>
        <AuthorList>
          <Author>
            <LastName>Researcher</LastName>
            <ForeName>Jane</ForeName>
          </Author>
        </AuthorList>
        <Abstract>
          <AbstractText>This paper explores ML applications in Kenya.</AbstractText>
        </Abstract>
      </Article>
      <MedlineJournalInfo>
        <Country>United States</Country>
      </MedlineJournalInfo>
    </MedlineCitation>
    <PubmedData>
      <History>
        <PubMedPubDate PubStatus="pubmed">
          <Year>2023</Year>
        </PubMedPubDate>
      </History>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""


def test_parse_pubmed_xml():
    """_parse_pubmed_xml correctly extracts title, author, journal."""
    articles = _parse_pubmed_xml(SAMPLE_PUBMED_XML)
    assert len(articles) == 1
    art = articles[0]
    assert art["title"] == "Machine Learning in Healthcare: A Kenyan Perspective"
    assert "Journal of Medical Informatics" in art["journal"]
    assert any("Researcher" in a for a in art["authors"])


def test_parse_pubmed_xml_invalid():
    """_parse_pubmed_xml returns [] for invalid XML."""
    articles = _parse_pubmed_xml("not xml at all")
    assert articles == []


def test_pubmed_render_text():
    """_render_text produces readable prose with key fields."""
    articles = [
        {
            "title": "ML in Healthcare",
            "year": "2023",
            "journal": "Nature",
            "authors": ["Jane Researcher", "Co Author"],
            "abstract": "Abstract text here.",
        }
    ]
    text = pubmed_render("Jane Researcher", articles)
    assert "Jane Researcher" in text
    assert "ML in Healthcare" in text
    assert "Nature" in text
    assert "2023" in text


@pytest.mark.anyio
@respx.mock
async def test_fetch_pubmed_author_success():
    """fetch_pubmed_author returns a CollectedSource with publication text."""
    respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        return_value=httpx.Response(200, json=SAMPLE_PUBMED_ESEARCH)
    )
    respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi").mock(
        return_value=httpx.Response(200, text=SAMPLE_PUBMED_XML)
    )

    result = await fetch_pubmed_author("Jane Researcher")

    assert result is not None
    assert isinstance(result, CollectedSource)
    assert result.source_type == "publication"
    assert "pubmed.ncbi.nlm.nih.gov" in result.domain
    assert "Machine Learning in Healthcare" in result.text
    assert result.content_hash


@pytest.mark.anyio
@respx.mock
async def test_fetch_pubmed_author_no_results():
    """Returns None when PubMed returns no IDs."""
    respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": []}})
    )

    result = await fetch_pubmed_author("Very Unknown Person 12345")
    assert result is None


@pytest.mark.anyio
@respx.mock
async def test_fetch_pubmed_author_network_error():
    """Returns None on network error without raising."""
    respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        side_effect=httpx.ConnectError("Timeout")
    )

    result = await fetch_pubmed_author("Jane Researcher")
    assert result is None
