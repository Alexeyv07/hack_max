"""Несколько адресов на группу и выбранный дом участника.

Revision ID: 0019_chat_addresses
Revises: 0018_notify_blocked
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_chat_addresses"
down_revision: str | None = "0018_notify_blocked"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_addresses",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("address_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.chat_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("chat_id", "address_id"),
    )
    op.create_index("ix_chat_addresses_address_id", "chat_addresses", ["address_id"])
    op.execute(
        "INSERT INTO chat_addresses (chat_id, address_id) SELECT chat_id, address_id FROM chats"
    )
    op.add_column("users_chat", sa.Column("address_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_chat_address_id",
        "users_chat",
        "addresses",
        ["address_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # Уже подключённым пользователям оставляем их старый адрес и доступ к событиям.
    op.execute(
        "UPDATE users_chat SET address_id = ("
        "SELECT chats.address_id FROM chats WHERE chats.chat_id = users_chat.chat_id)"
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_chat_address_id", "users_chat", type_="foreignkey")
    op.drop_column("users_chat", "address_id")
    op.drop_index("ix_chat_addresses_address_id", table_name="chat_addresses")
    op.drop_table("chat_addresses")
