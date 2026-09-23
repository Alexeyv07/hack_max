"""Хранилище текстовых сообщений для #итого и надёжный ID cursor.

Revision ID: 0017_notify_chat_messages
Revises: 0016_membership_only
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_notify_chat_messages"
down_revision: str | None = "0016_membership_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notify_chat_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.chat_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "message_id", name="uq_notify_chat_message_chat_mid"),
    )
    op.create_index("ix_notify_chat_messages_chat_id_id", "notify_chat_messages", ["chat_id", "id"])
    op.add_column("notify_digests", sa.Column("last_message_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("notify_digests", "last_message_id")
    op.drop_index("ix_notify_chat_messages_chat_id_id", table_name="notify_chat_messages")
    op.drop_table("notify_chat_messages")
