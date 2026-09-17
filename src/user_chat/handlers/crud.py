"""Создание и поиск чатов. Транзакцией управляет вызывающий session_scope."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from user_chat.db import ChatRow
from user_chat.models.chat import Chat, ChatCreate


def _to_domain(row: ChatRow) -> Chat:
    return Chat(
        chat_id=row.chat_id,
        address_id=row.address_id,
        title=row.title,
        invite_link=row.invite_link,
    )


def create_chat(session: Session, data: ChatCreate) -> Chat:
    """Привязать MAX-чат к существующему адресу; повторный chat_id — ошибка."""
    if type(data.chat_id) is not int or not -(2**63) <= data.chat_id < 2**63:
        raise ValueError("chat_id должен быть целым 64-битным идентификатором MAX")
    title = data.title.strip()
    if not 1 <= len(title) <= 255:
        raise ValueError("title должен содержать от 1 до 255 символов")
    invite_link = data.invite_link.strip() if data.invite_link is not None else None
    if invite_link is not None and not 1 <= len(invite_link) <= 2048:
        raise ValueError("invite_link должен содержать от 1 до 2048 символов либо быть None")
    address = session.get(AddressRow, data.address_id)
    if address is None:
        raise ValueError(f"Адрес id={data.address_id} не найден")
    if session.get(ChatRow, data.chat_id) is not None:
        raise ValueError(f"Чат chat_id={data.chat_id} уже существует")
    row = ChatRow(chat_id=data.chat_id, address=address, title=title, invite_link=invite_link)
    session.add(row)
    session.flush()
    return _to_domain(row)


def get_chat(session: Session, chat_id: int) -> Chat | None:
    row = session.get(ChatRow, chat_id)
    return _to_domain(row) if row is not None else None


def list_chats_by_address(session: Session, address_id: int) -> list[Chat]:
    """Все чаты адреса, включая чаты без участников."""
    rows = session.scalars(
        select(ChatRow).where(ChatRow.address_id == address_id).order_by(ChatRow.chat_id)
    )
    return [_to_domain(row) for row in rows]
