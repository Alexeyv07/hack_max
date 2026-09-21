"""KAN notify: состояние дайджестов, личных пушей и event cursor.

Revision ID: 0014_notify_workers
Revises: 0013_events_active_window
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_notify_workers"
down_revision: str | None = "0013_events_active_window"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notify_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_id", name="uq_notify_delivery_user_event"),
    )
    op.create_index("ix_notify_deliveries_user_id", "notify_deliveries", ["user_id"], unique=False)
    op.create_index(
        "ix_notify_deliveries_event_id", "notify_deliveries", ["event_id"], unique=False
    )
    op.create_index(
        "ix_notify_deliveries_acked_at", "notify_deliveries", ["acked_at"], unique=False
    )
    op.create_index(
        "ix_notify_deliveries_last_sent_at",
        "notify_deliveries",
        ["last_sent_at"],
        unique=False,
    )

    op.create_table(
        "notify_digests",
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("last_digest_date", sa.Date(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.chat_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id"),
    )

    op.create_table(
        "notify_cursors",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("last_event_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("notify_cursors")
    op.drop_table("notify_digests")
    op.drop_index("ix_notify_deliveries_last_sent_at", table_name="notify_deliveries")
    op.drop_index("ix_notify_deliveries_acked_at", table_name="notify_deliveries")
    op.drop_index("ix_notify_deliveries_event_id", table_name="notify_deliveries")
    op.drop_index("ix_notify_deliveries_user_id", table_name="notify_deliveries")
    op.drop_table("notify_deliveries")
