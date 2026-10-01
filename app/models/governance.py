"""
Governance ORM models.

Covers the full audit and correction surface:
  - Query      — every search request is logged (accountable use)
  - MergeLog   — history of entity resolution decisions
  - Dispute    — correction and removal requests from data subjects
  - Suppression — opt-out list; suppressed keys are never re-ingested
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DisputeStatus(str, enum.Enum):
    open = "open"
    under_review = "under_review"
    resolved = "resolved"
    rejected = "rejected"


class MergeDecision(str, enum.Enum):
    merged = "merged"
    kept_separate = "kept_separate"
    deferred = "deferred"


class Query(Base):
    """Immutable audit record of every search performed."""

    __tablename__ = "queries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # The full parsed query (name, hints, variants) stored as JSON
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Stated purpose collected at query time (required for accountable use)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"<Query id={self.id} user={self.user_id}>"


class MergeLog(Base):
    """Records every entity-resolution decision — supports audits and corrections."""

    __tablename__ = "merge_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    person_id_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True
    )
    person_id_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[MergeDecision] = mapped_column(String(16), nullable=False)
    # Full signal vector used to reach this decision
    signals_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<MergeLog {self.person_id_a} ↔ {self.person_id_b} → {self.decision}>"


class Dispute(Base):
    """Correction or removal request submitted by a data subject or their representative."""

    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitter: Mapped[str] = mapped_column(String(512), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[DisputeStatus] = mapped_column(
        String(16), nullable=False, default=DisputeStatus.open
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    person: Mapped["Person"] = relationship("Person", back_populates="disputes")  # noqa: F821
    claim: Mapped["Claim"] = relationship("Claim", back_populates="disputes")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Dispute id={self.id} status={self.status}>"


class Suppression(Base):
    """
    Opt-out list.

    A match_key (e.g. a canonical name hash) in this table means
    that identity is never collected or displayed again.
    """

    __tablename__ = "suppressions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    match_key: Mapped[str] = mapped_column(
        String(512), unique=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Suppression key={self.match_key!r}>"
