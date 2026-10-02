"""
Pydantic schemas for Exportable Evidence Reports.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.search import ClaimOut, ConflictFlag, ProfileSummary, StalenessFlag


class EvidenceReport(BaseModel):
    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    disclaimer: str = (
        "Possible match only. This due-diligence evidence report is compiled "
        "exclusively from publicly accessible sources with explicit provenance, "
        "without private data inference. No personal identity is definitively established."
    )
    person_id: uuid.UUID
    canonical_name: str
    status: str
    summary: ProfileSummary | None = None
    claims_count: int
    unique_sources_count: int
    claims: list[ClaimOut]
    conflict_flags: list[ConflictFlag] = []
    staleness_flags: list[StalenessFlag] = []
    sha256_integrity_hash: str
