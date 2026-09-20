"""KAN-7: отличать реальные групповые чаты от legacy DIALOG-записей.

Revision ID: 0012_chat_group_type
Revises: 0011_chat_link
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_chat_group_type"
down_revision: str | None = "0011_chat_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("chat_type", sa.String(16), nullable=True))
    op.create_index("ix_chats_chat_type", "chats", ["chat_type"], unique=False)

    # Старый KAN-7 mock писал личный DIALOG в chats, поэтому нельзя пометить все
    # исторические записи как group. Подтверждённые новым lifecycle группы уже
    # имеют chat_links.chat_id — только их безопасно восстановить как `chat`.
    op.execute(
        sa.text(
            """
            UPDATE chats
            SET chat_type = 'chat'
            WHERE chat_id IN (
                SELECT DISTINCT chat_id
                FROM chat_links
                WHERE chat_id IS NOT NULL
                  AND status IN ('connected', 'waiting_join')
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_chats_chat_type", table_name="chats")
    op.drop_column("chats", "chat_type")
