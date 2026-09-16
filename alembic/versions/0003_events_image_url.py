"""Добавить image_url к events.

Revision ID: 0003_events_image_url
Revises: 0002_create_events
Create Date: 2026-09-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_events_image_url"
down_revision: str | None = "0002_create_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("image_url", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "image_url")
