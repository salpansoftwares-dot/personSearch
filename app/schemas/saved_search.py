"""
Pydantic schemas for Saved Searches.

Saved searches store repeatable query criteria (name + hints + purpose)
without storing personal data or caching stale results.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.search import SearchRequest


class SavedSearchCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=256, description="Human-readable label for the saved search")
    query: SearchRequest | dict[str, Any] = Field(..., description="Search parameters including name and hints")
    user_id: str | None = Field(None, max_length=256, description="Optional user or session identifier")


class SavedSearchUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=256)
    query: SearchRequest | dict[str, Any] | None = None


class SavedSearchOut(BaseModel):
    id: uuid.UUID
    label: str
    query_json: dict[str, Any]
    user_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
