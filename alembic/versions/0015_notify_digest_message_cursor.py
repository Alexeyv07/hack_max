"""KAN notify: cursor последнего суммаризированного сообщения.

Revision ID: 0015_notify_digest_cursor
Revises: 0014_notify_workers
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_notify_digest_cursor"
down_revision: str | None = "0014_notify_workers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notify_digests",
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notify_digests", "last_message_at")
