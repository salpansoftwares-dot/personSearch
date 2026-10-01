"""
Pydantic schemas for the /api/v1/search endpoint.

These are the shapes of data coming in from the client and going out
to the client. They are deliberately separate from ORM models.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── Request ────────────────────────────────────────────────────────────────────

class SearchHints(BaseModel):
    """Optional contextual hints that narrow candidate discovery."""
    organization: str | None = Field(None, description="Employer or institution name")
    sector: str | None = Field(None, description="Industry sector, e.g. 'technology'")
    country: str | None = Field(None, description="ISO 3166-1 alpha-2 country code, e.g. 'KE'")
    role: str | None = Field(None, description="Job title or role, e.g. 'Software Engineer'")


class SearchRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=256, description="Full name to search for")
    hints: SearchHints = Field(default_factory=SearchHints)
    purpose: str | None = Field(
        None,
        max_length=512,
        description="Stated reason for the search (collected for accountable use)",
    )


# ── Response ───────────────────────────────────────────────────────────────────

class EvidenceItem(BaseModel):
    source_url: str
    source_type: str
    excerpt: str
    retrieved_at: datetime


class ClaimOut(BaseModel):
    claim_id: uuid.UUID
    type: str
    value: str
    confidence: float
    evidence: list[EvidenceItem]


class PersonResult(BaseModel):
    person_id: uuid.UUID
    # Architecture requirement: always say "possible match", never definitive.
    label: str = "possible match"
    confidence: float
    canonical_name: str
    claims: list[ClaimOut]
    # IDs of other person clusters that are plausible but not selected
    alternatives: list[uuid.UUID] = []


class SearchResponse(BaseModel):
    query_id: uuid.UUID
    results: list[PersonResult]
    # Hints as parsed / expanded by the query understanding module
    parsed_hints: dict = {}
