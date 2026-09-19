"""Курсоры парсера УК/ЖЭК (KAN-28).

Revision ID: 0010_mc_parser
Revises: 0009_create_chats
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_mc_parser"
down_revision: str | None = "0009_create_chats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mc_parser_cursors",
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


def downgrade() -> None:
    op.drop_table("mc_parser_cursors")
