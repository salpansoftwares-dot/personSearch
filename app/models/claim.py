"""
Claim ORM model.

A claim is one structured fact extracted from a source — e.g.
occupation = "Software Engineer". It always carries the verbatim
evidence span it was extracted from and a confidence score.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ClaimType(str, enum.Enum):
    """
    Allowlist of permitted claim types.

    This enum is the scope filter in code — any claim whose type is not
    listed here is rejected before storage.
    """
    occupation = "occupation"
    organization = "organization"
    role = "role"
    publication = "publication"
    talk = "talk"
    education = "education"
    profile_url = "profile_url"
    project = "project"


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claim_type: Mapped[ClaimType] = mapped_column(String(32), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    # The verbatim text from the source that supports this claim.
    # If this cannot be found in the source, the claim is rejected.
    evidence_span: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # 0.0 – 1.0; derives from source quality and corroboration
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    # Retention: when set, the claim is considered expired and eligible for sweep.
    # Populated by upsert_source based on settings.claim_expiry_days.
    expires_at: Mapped["datetime | None"] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # True once the retention sweep or a re-verification run has flagged this claim as stale.
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    source: Mapped["Source"] = relationship("Source", back_populates="claims")  # noqa: F821
    person_claims: Mapped[list["PersonClaim"]] = relationship(  # noqa: F821
        "PersonClaim", back_populates="claim", cascade="all, delete-orphan"
    )
    person_names: Mapped[list["PersonName"]] = relationship(  # noqa: F821
        "PersonName", back_populates="claim"
    )
    disputes: Mapped[list["Dispute"]] = relationship(  # noqa: F821
        "Dispute", back_populates="claim"
    )

    def __repr__(self) -> str:
        return f"<Claim id={self.id} type={self.claim_type} value={self.value!r}>"
