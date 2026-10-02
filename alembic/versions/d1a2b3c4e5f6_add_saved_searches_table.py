"""Add saved_searches table.

Revision ID: d1a2b3c4e5f6
Revises: c03fdce1c17d
Create Date: 2026-10-02 20:55:00.000000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1a2b3c4e5f6"
down_revision: Union[str, None] = "c03fdce1c17d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_searches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("query_json", postgresql.JSONB(), nullable=False),
        sa.Column("user_id", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_saved_searches_user_id",
        "saved_searches",
        ["user_id"],
    )
    op.create_index(
        "ix_saved_searches_user_id_created",
        "saved_searches",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_saved_searches_user_id_created", table_name="saved_searches")
    op.drop_index("ix_saved_searches_user_id", table_name="saved_searches")
    op.drop_table("saved_searches")
