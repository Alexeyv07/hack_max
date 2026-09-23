"""Закрыть незавершённые заявки старого механизма admin approve.

Revision ID: 0016_membership_only
Revises: 0015_notify_digest_cursor
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_membership_only"
down_revision: str | None = "0015_notify_digest_cursor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE chat_links SET status = 'cancelled' "
            "WHERE status IN ('waiting_approval', 'approval_sent')"
        )
    )


def downgrade() -> None:
    # Предыдущие статусы решений администратора восстановить достоверно нельзя.
    pass
