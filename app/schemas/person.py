"""
Pydantic schemas for person profiles and dispute submissions.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.search import ClaimOut


# ── Person profile ─────────────────────────────────────────────────────────────

class PersonProfile(BaseModel):
    person_id: uuid.UUID
    canonical_name: str
    status: str
    updated_at: datetime
    claims: list[ClaimOut]
    alternatives: list[uuid.UUID] = []


# ── Dispute / removal request ──────────────────────────────────────────────────

class DisputeRequest(BaseModel):
    person_id: uuid.UUID | None = Field(None, description="Person cluster being disputed")
    claim_id: uuid.UUID | None = Field(None, description="Specific claim being disputed")
    submitter: str = Field(..., max_length=512, description="Name or reference of submitter")
    reason: str | None = Field(None, max_length=2048, description="Reason for the request")


class DisputeResponse(BaseModel):
    dispute_id: uuid.UUID
    status: str
    message: str
    created_at: datetime
