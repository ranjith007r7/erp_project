"""notifications: read_at, so read messages sit in a 7-day temporary archive

Revision ID: a3d6e8b1c479
Revises: f2c8a5d1e947
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3d6e8b1c479"
down_revision: Union[str, None] = "f2c8a5d1e947"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("read_at", sa.DateTime(), nullable=True))
    # messages already read get the date they were created as their read date (so old ones are purged at the next fetch)
    op.execute("UPDATE notifications SET read_at = created_at WHERE is_read = true AND read_at IS NULL")
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "is_read", "read_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_column("notifications", "read_at")
