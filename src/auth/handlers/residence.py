"""Личный адрес пользователя отдельно от связей users_chat / chat_addresses."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from auth.db.user import UserRow


def get_personal_address(session: Session, max_user_id: int) -> AddressRow | None:
    address_id = session.scalar(
        select(UserRow.address_id).where(UserRow.max_user_id == max_user_id)
    )
    return session.get(AddressRow, address_id) if address_id is not None else None


def set_personal_address(session: Session, *, max_user_id: int, address_id: int) -> None:
    """Сохраняем дом только существующего MAX-пользователя и только из каталога."""
    user = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if user is None:
        raise ValueError("Сначала откройте бота командой /start")
    if session.get(AddressRow, address_id) is None:
        raise ValueError("Адрес не найден")
    user.address_id = address_id
    session.flush()
