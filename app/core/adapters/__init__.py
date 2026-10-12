"""
Source adapters package.

Each adapter fetches structured data from a specific API or public web source
and returns a CollectedSource.

V2 adapters:
  - orcid_adapter          → ORCID researcher profiles
  - semantic_scholar_adapter → Semantic Scholar papers & authors
  - pubmed_adapter         → PubMed / NCBI publications
  - university_adapter     → University faculty pages & Kenyan professional registries
  - patents_adapter        → WIPO PatentScope, Google Patents, KIPI
  - conference_adapter     → ACM DL, IEEE Xplore, DBLP conference papers
"""

from app.core.adapters.orcid_adapter import fetch_orcid_profile
from app.core.adapters.semantic_scholar_adapter import fetch_semantic_scholar_author
from app.core.adapters.pubmed_adapter import fetch_pubmed_author
from app.core.adapters.university_adapter import fetch_university_and_registry
from app.core.adapters.patents_adapter import fetch_patents
from app.core.adapters.conference_adapter import fetch_conference_papers

__all__ = [
    "fetch_orcid_profile",
    "fetch_semantic_scholar_author",
    "fetch_pubmed_author",
    "fetch_university_and_registry",
    "fetch_patents",
    "fetch_conference_papers",
]
