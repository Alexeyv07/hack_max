"""KAN-7: заявки/токены подключения чатов.

Revision ID: 0010_create_chat_links
Revises: 0009_create_chats
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_create_chat_links"
down_revision: str | None = "0009_create_chats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_links",
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("address_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("token"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.chat_id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('pending_bot', 'pending_admin', 'ready', 'cancelled')",
            name="ck_chat_links_status",
        ),
    )
    op.create_index("ix_chat_links_address_id", "chat_links", ["address_id"], unique=False)
    op.create_index(
        "ix_chat_links_created_by_user_id", "chat_links", ["created_by_user_id"], unique=False
    )
    op.create_index("ix_chat_links_chat_id", "chat_links", ["chat_id"], unique=False)
    op.create_index("ix_chat_links_status", "chat_links", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chat_links_status", table_name="chat_links")
    op.drop_index("ix_chat_links_chat_id", table_name="chat_links")
    op.drop_index("ix_chat_links_created_by_user_id", table_name="chat_links")
    op.drop_index("ix_chat_links_address_id", table_name="chat_links")
    op.drop_table("chat_links")
