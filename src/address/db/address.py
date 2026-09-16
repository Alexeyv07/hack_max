"""Таблица адресов: один почтовый индекс может относиться к нескольким домам."""

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from project.database import Base


class AddressRow(Base):
    __tablename__ = "addresses"
    # Проверка формата postal_code остаётся в PostgreSQL-миграции: SQLite из тестов
    # не поддерживает оператор ~, поэтому в переносимую ORM metadata её не дублируем.
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_addresses_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_addresses_longitude"),
        CheckConstraint("length(trim(address_text)) > 0", name="ck_addresses_text"),
    )

    # Стабильный короткий ключ: на него ссылаются события и другие доменные таблицы.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    postal_code: Mapped[str | None] = mapped_column(String(6), index=True, nullable=True)
    # Текст остаётся естественным уникальным ключом для идемпотентной загрузки справочника.
    address_text: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    # None — тип дома неизвестен, False — многоквартирный, True — индивидуальный.
    is_private: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
