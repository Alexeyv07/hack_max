"""События: published_at для timeliness в весе ленты.

Revision ID: 0008_events_published_at
Revises: 0007_address_components_geo_by
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_events_published_at"
down_revision: str | None = "0007_address_components_geo_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_events_published_at", "events", ["published_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_events_published_at", table_name="events")
    op.drop_column("events", "published_at")
