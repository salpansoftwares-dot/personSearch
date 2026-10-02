"""
SavedSearch ORM model.

Stores a named, repeatable search query (name + hints) for a user/session.
No personal data is stored; this is a saved *query*, not a cached result.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON

from app.database import Base


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Caller-supplied label for this saved search
    label: Mapped[str] = mapped_column(String(256), nullable=False)

    # The raw search payload (name + hints) stored as JSON
    query_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Opaque user / session identifier (no auth yet — client-supplied string)
    user_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # Fast look-up of all saved searches for a user
        Index("ix_saved_searches_user_id_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SavedSearch id={self.id} label={self.label!r} user={self.user_id!r}>"
