"""
Source adapters package.

Each adapter fetches structured data from a specific API
(rather than scraping HTML) and returns a CollectedSource.
"""

from app.core.adapters.orcid_adapter import fetch_orcid_profile
from app.core.adapters.semantic_scholar_adapter import fetch_semantic_scholar_author
from app.core.adapters.pubmed_adapter import fetch_pubmed_author

__all__ = [
    "fetch_orcid_profile",
    "fetch_semantic_scholar_author",
    "fetch_pubmed_author",
]
