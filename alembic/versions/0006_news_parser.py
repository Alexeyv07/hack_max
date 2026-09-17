"""Связь events ↔ addresses вместо lat/lon + news parser cursors.

Revision ID: 0006_news_parser
Revises: 0005_event_address_fk
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_news_parser"
down_revision: str | None = "0005_event_address_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_parser_cursors",
        sa.Column("source_key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("backfill_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("oldest_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("newest_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("listing_cursor", sa.String(length=512), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_events_source_msg",
        "events",
        ["source", "source_msg_id"],
        unique=True,
        postgresql_where=sa.text("source_msg_id IS NOT NULL"),
        sqlite_where=sa.text("source_msg_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_events_source_msg", table_name="events")
    op.drop_table("news_parser_cursors")
