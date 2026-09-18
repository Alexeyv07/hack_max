"""Связать events с addresses: city/street/house + events.geo_by.

Revision ID: 0007_address_components_geo_by
Revises: 0006_news_parser
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_address_components_geo_by"
down_revision: str | None = "0006_news_parser"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HOUSE_PREFIX = re.compile(r"^(?:д\.?|дом)\s*(?P<house>.+)$", re.IGNORECASE)
_HOUSE_INLINE = re.compile(
    r"\b(?:д\.?|дом)\s+(?P<house>[0-9]+[а-яА-Яa-zA-Z]?(?:\s*[кк]\s*[0-9]+[а-яА-Я]?)?"
    r"(?:\s*[сc]\s*[0-9]+[а-яА-Я]?)?)\s*$",
    re.IGNORECASE,
)


def _parse_components(address_text: str) -> tuple[str | None, str | None, str | None]:
    parts = [part.strip() for part in address_text.split(",") if part.strip()]
    if not parts:
        return None, None, None
    city = parts[0] or None
    house: str | None = None
    street_parts: list[str] = []
    for part in parts[1:]:
        match = _HOUSE_PREFIX.match(part)
        if match:
            house = match.group("house").strip()
            continue
        street_parts.append(part)
    street = ", ".join(street_parts) if street_parts else None
    if street and house is None:
        inline = _HOUSE_INLINE.search(street)
        if inline:
            house = inline.group("house").strip()
            street = _HOUSE_INLINE.sub("", street).strip(" ,") or None
    return city, street, house


def upgrade() -> None:
    op.add_column("addresses", sa.Column("city", sa.String(length=128), nullable=True))
    op.add_column("addresses", sa.Column("street", sa.String(length=512), nullable=True))
    op.add_column("addresses", sa.Column("house", sa.String(length=64), nullable=True))
    op.create_index("ix_addresses_city", "addresses", ["city"], unique=False)

    op.add_column("events", sa.Column("geo_by", sa.String(length=16), nullable=True))
    op.create_index("ix_events_geo_by", "events", ["geo_by"], unique=False)

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, address_text FROM addresses")).mappings().all()
    update = sa.text(
        "UPDATE addresses SET city = :city, street = :street, house = :house WHERE id = :id"
    )
    for row in rows:
        city, street, house = _parse_components(row["address_text"])
        connection.execute(
            update,
            {"id": row["id"], "city": city, "street": street, "house": house},
        )


def downgrade() -> None:
    op.drop_index("ix_events_geo_by", table_name="events")
    op.drop_column("events", "geo_by")
    op.drop_index("ix_addresses_city", table_name="addresses")
    op.drop_column("addresses", "house")
    op.drop_column("addresses", "street")
    op.drop_column("addresses", "city")
