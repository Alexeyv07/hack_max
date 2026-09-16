"""Создание таблицы addresses. Загрузка справочника — отдельный шаг.

Revision ID: 0004_create_addresses
Revises: 0003_events_image_url
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_create_addresses"
down_revision: str | None = "0003_events_image_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "addresses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("postal_code", sa.String(6), nullable=True),
        sa.Column("address_text", sa.String(1000), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address_text", name="uq_addresses_address_text"),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_addresses_latitude"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_addresses_longitude"),
        sa.CheckConstraint(
            "postal_code IS NULL OR postal_code ~ '^[0-9]{6}$'",
            name="ck_addresses_postal_code",
        ),
        sa.CheckConstraint("length(trim(address_text)) > 0", name="ck_addresses_text"),
    )
    op.create_index("ix_addresses_postal_code", "addresses", ["postal_code"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_addresses_postal_code", table_name="addresses")
    op.drop_table("addresses")
