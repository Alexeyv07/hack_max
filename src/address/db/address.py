"""Таблица адресов: один почтовый индекс может относиться к нескольким домам."""

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from project.database import Base


class AddressRow(Base):
    __tablename__ = "addresses"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_addresses_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_addresses_longitude"),
        CheckConstraint(
            "postal_code IS NULL OR postal_code ~ '^[0-9]{6}$'",
            name="ck_addresses_postal_code",
        ),
        CheckConstraint("length(trim(address_text)) > 0", name="ck_addresses_text"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    postal_code: Mapped[str | None] = mapped_column(String(6), index=True, nullable=True)
    address_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    # None — тип дома неизвестен, False — многоквартирный, True — индивидуальный.
    is_private: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
