"""Останавливать повторы при заблокированном личном диалоге MAX.

Revision ID: 0018_notify_blocked
Revises: 0017_notify_chat_messages
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_notify_blocked"
down_revision: str | None = "0017_notify_chat_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("notify_blocked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("notify_blocked_reason", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "notify_blocked_reason")
    op.drop_column("users", "notify_blocked_at")
