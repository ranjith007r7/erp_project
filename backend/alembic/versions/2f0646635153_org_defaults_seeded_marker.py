"""org defaults seeded marker

Revision ID: 2f0646635153
Revises: 3ccef45d908c
Create Date: 2026-10-08 15:39:40.407532

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f0646635153'
down_revision: Union[str, None] = '3ccef45d908c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('defaults_seeded_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('organizations', 'defaults_seeded_at')
