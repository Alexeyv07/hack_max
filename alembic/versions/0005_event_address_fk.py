"""Связать events с addresses вместо хранения lat/lon в events.

Revision ID: 0005_event_address_fk
Revises: 0004_create_addresses
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_event_address_fk"
down_revision: str | None = "0004_create_addresses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("address_id", sa.Integer(), nullable=True))
    op.create_index("ix_events_address_id", "events", ["address_id"], unique=False)
    op.create_foreign_key(
        "fk_events_address_id_addresses",
        "events",
        "addresses",
        ["address_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Если старый mock-event уже указывает ровно в одну точку справочника,
    # сохраняем связь автоматически. Неоднозначные/неизвестные координаты не угадываем.
    op.execute(
        """
        WITH unique_coordinates AS (
            SELECT
                latitude::double precision AS lat,
                longitude::double precision AS lon,
                min(id) AS address_id
            FROM addresses
            GROUP BY latitude, longitude
            HAVING count(*) = 1
        )
        UPDATE events AS event
        SET address_id = point.address_id
        FROM unique_coordinates AS point
        WHERE event.lat = point.lat AND event.lon = point.lon
        """
    )

    # После появления Address единственный источник геопозиции события — связанная запись.
    op.drop_column("events", "lat")
    op.drop_column("events", "lon")


def downgrade() -> None:
    op.add_column("events", sa.Column("lon", sa.Float(), nullable=True))
    op.add_column("events", sa.Column("lat", sa.Float(), nullable=True))
    op.execute(
        """
        UPDATE events AS event
        SET lat = address.latitude::double precision,
            lon = address.longitude::double precision
        FROM addresses AS address
        WHERE event.address_id = address.id
        """
    )

    op.drop_constraint("fk_events_address_id_addresses", "events", type_="foreignkey")
    op.drop_index("ix_events_address_id", table_name="events")
    op.drop_column("events", "address_id")
