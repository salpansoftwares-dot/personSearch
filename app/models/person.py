"""
Person-related ORM models.

Persons are clusters of claims. The same claim can be re-attributed
when clusters are split or corrected via the merge_log.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PersonStatus(str, enum.Enum):
    active = "active"
    suppressed = "suppressed"  # opt-out — never re-ingested


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    canonical_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    status: Mapped[PersonStatus] = mapped_column(
        String(16), nullable=False, default=PersonStatus.active
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    person_claims: Mapped[list["PersonClaim"]] = relationship(
        "PersonClaim", back_populates="person", cascade="all, delete-orphan"
    )
    person_names: Mapped[list["PersonName"]] = relationship(
        "PersonName", back_populates="person", cascade="all, delete-orphan"
    )
    disputes: Mapped[list["Dispute"]] = relationship(  # noqa: F821
        "Dispute", back_populates="person"
    )

    def __repr__(self) -> str:
        return f"<Person id={self.id} name={self.canonical_name!r}>"


class PersonClaim(Base):
    """Junction: links a person cluster to a claim with a link confidence score."""

    __tablename__ = "person_claims"

    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.id", ondelete="CASCADE"),
        primary_key=True,
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        primary_key=True,
    )
    link_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    link_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────────────
    person: Mapped["Person"] = relationship("Person", back_populates="person_claims")
    claim: Mapped["Claim"] = relationship("Claim", back_populates="person_claims")  # noqa: F821


class PersonName(Base):
    """All name variants observed for a person across sources."""

    __tablename__ = "person_names"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    # Which claim introduced this name variant
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    person: Mapped["Person"] = relationship("Person", back_populates="person_names")
    claim: Mapped["Claim"] = relationship("Claim", back_populates="person_names")  # noqa: F821
