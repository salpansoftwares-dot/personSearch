"""
Source ORM model.

Tracks every URL the collector has fetched. Claims are linked here
so we always know where a piece of information came from.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. linkedin_profile | github_profile | company_page | conference | press
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # SHA-256 of the raw page text at retrieval time — used for staleness detection.
    # A changed hash on re-fetch means the page content has changed and claims need re-verification.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=False)
    # True once this source has been flagged as stale (content changed or expiry passed)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    claims: Mapped[list["Claim"]] = relationship(  # noqa: F821
        "Claim", back_populates="source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Source id={self.id} domain={self.domain}>"
