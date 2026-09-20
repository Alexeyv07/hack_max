"""KAN-7: district в addresses и заявки chat_links.

Revision ID: 0011_chat_link
Revises: 0010_mc_parser
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_chat_link"
down_revision: str | None = "0010_mc_parser"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("addresses", sa.Column("district", sa.String(256), nullable=True))
    op.create_index("ix_addresses_district", "addresses", ["district"], unique=False)

    # Уже загруженный snapshot содержит locality в address_text: Москва, locality, улица, д. N.
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, address_text, street FROM addresses")).mappings()
    updates: list[dict[str, object]] = []
    for row in rows:
        parts = [part.strip() for part in row["address_text"].split(",") if part.strip()]
        if len(parts) < 4 or not row["street"]:
            continue
        try:
            street_index = next(i for i, part in enumerate(parts) if part == row["street"])
        except StopIteration:
            continue
        district = ", ".join(parts[1:street_index]) or None
        if district:
            updates.append({"id": row["id"], "district": district[:256]})
    if updates:
        connection.execute(
            sa.text("UPDATE addresses SET district=:district WHERE id=:id"),
            updates,
        )

    op.create_table(
        "chat_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token", sa.String(32), nullable=False),
        sa.Column("requester_user_id", sa.Integer(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=True),
        sa.Column("address_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_chat_links_token"),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.chat_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_chat_links_requester", "chat_links", ["requester_user_id"])
    op.create_index("ix_chat_links_address", "chat_links", ["address_id"])
    op.create_index("ix_chat_links_status", "chat_links", ["status"])


def downgrade() -> None:
    op.drop_index("ix_chat_links_status", table_name="chat_links")
    op.drop_index("ix_chat_links_address", table_name="chat_links")
    op.drop_index("ix_chat_links_requester", table_name="chat_links")
    op.drop_table("chat_links")
    op.drop_index("ix_addresses_district", table_name="addresses")
    op.drop_column("addresses", "district")
