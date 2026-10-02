"""add_summary_json_to_persons

Revision ID: c03fdce1c17d
Revises: 06ad7ef11fc8
Create Date: 2026-10-02 16:55:27.081154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c03fdce1c17d'
down_revision: Union[str, None] = '06ad7ef11fc8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('persons', sa.Column('summary_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('persons', 'summary_json')
