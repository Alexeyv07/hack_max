"""Создание таблицы events.

Revision ID: 0002_create_events
Revises: 0001_create_users
Create Date: 2026-09-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_create_events"
down_revision: str | None = "0001_create_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_msg_id", sa.String(length=128), nullable=True),
        sa.Column("disaster_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_importance", "events", ["importance"], unique=False)
    op.create_index("ix_events_source", "events", ["source"], unique=False)
    op.create_index("ix_events_weight", "events", ["weight"], unique=False)
    op.create_index("ix_events_source_msg_id", "events", ["source_msg_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_events_source_msg_id", table_name="events")
    op.drop_index("ix_events_weight", table_name="events")
    op.drop_index("ix_events_source", table_name="events")
    op.drop_index("ix_events_importance", table_name="events")
    op.drop_table("events")
