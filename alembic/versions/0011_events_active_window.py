"""События: active_from / active_to (окно действия новости).

Revision ID: 0011_events_active_window
Revises: 0010_mc_parser
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_events_active_window"
down_revision: str | None = "0010_mc_parser"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("active_to", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_events_active_from", "events", ["active_from"], unique=False)
    op.create_index("ix_events_active_to", "events", ["active_to"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_events_active_to", table_name="events")
    op.drop_index("ix_events_active_from", table_name="events")
    op.drop_column("events", "active_to")
    op.drop_column("events", "active_from")
