"""Адрес на уровне приложения, без зависимости от SQLAlchemy."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Address:
    id: int | None
    postal_code: str | None
    address_text: str
    latitude: Decimal
    longitude: Decimal
    is_private: bool | None = None
