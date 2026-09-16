"""Создание таблицы addresses. Загрузка справочника — отдельный шаг."""

import sqlalchemy as sa
from alembic import op

revision = "0002_create_addresses"
down_revision = "0001_create_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE addresses_id_seq")

    op.create_table(
        "addresses",
        sa.Column(
            "id",
            sa.Integer(),
            server_default=sa.text("nextval('addresses_id_seq')"),
            nullable=False,
        ),
        sa.Column("postal_code", sa.String(6), nullable=True),
        sa.Column("address_text", sa.String(1000), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("address_text"),
        sa.CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_addresses_latitude",
        ),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_addresses_longitude",
        ),
        sa.CheckConstraint(
            "postal_code IS NULL OR postal_code ~ '^[0-9]{6}$'",
            name="ck_addresses_postal_code",
        ),
        sa.CheckConstraint(
            "length(trim(address_text)) > 0",
            name="ck_addresses_text",
        ),
    )

    op.execute("ALTER SEQUENCE addresses_id_seq OWNED BY addresses.id")

    op.create_index(
        "ix_addresses_postal_code",
        "addresses",
        ["postal_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_addresses_postal_code",
        table_name="addresses",
    )
    op.drop_table("addresses")
