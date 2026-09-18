"""Чаты соседей и участники.

Revision ID: 0006_create_chats
Revises: 0005_event_address_fk
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_create_chats"
down_revision: str | None = "0005_event_address_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("invite_link", sa.String(2048), nullable=True),
        sa.Column("address_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("chat_id"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_chats_address_id", "chats", ["address_id"], unique=False)
    op.create_table(
        "users_chat",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "chat_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.chat_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_users_chat_chat_id", "users_chat", ["chat_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_chat_chat_id", table_name="users_chat")
    op.drop_table("users_chat")
    op.drop_index("ix_chats_address_id", table_name="chats")
    op.drop_table("chats")
