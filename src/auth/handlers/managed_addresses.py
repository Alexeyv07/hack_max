"""Личные адреса, которые пользователь выбрал в подключённых домовых чатах."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from auth.db.user import UserRow
from user_chat.db import ChatRow, users_chat
from user_chat.handlers.membership import linked_group_ids


@dataclass(frozen=True, slots=True)
class ManagedAddress:
    id: int
    text: str


def list_managed_addresses(session: Session, max_user_id: int) -> list[ManagedAddress]:
    """Только собственные подтверждённые адреса, не все дома общих чатов."""
    user = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if user is None:
        return []

    rows = session.execute(
        select(AddressRow.id, AddressRow.address_text)
        .join(users_chat, users_chat.c.address_id == AddressRow.id)
        .join(ChatRow, ChatRow.chat_id == users_chat.c.chat_id)
        .where(users_chat.c.user_id == user.id, ChatRow.chat_type == "chat")
        .distinct()
        .order_by(AddressRow.address_text, AddressRow.id)
    ).all()

    addresses = {address_id: text for address_id, text in rows}

    # Личный адрес может отличаться от выбранных адресов в других группах.
    if (
        user.address_id is not None
        and user.address_id not in addresses
        and linked_group_ids(session, max_user_id, address_id=user.address_id)
    ):
        personal = session.get(AddressRow, user.address_id)
        if personal is not None:
            addresses[personal.id] = personal.address_text

    return [
        ManagedAddress(id_, text)
        for id_, text in sorted(addresses.items(), key=lambda x: (x[1], x[0]))
    ]


def remove_managed_address(session: Session, *, max_user_id: int, address_id: int) -> bool:
    """Убрать адрес только у пользователя. Членство и адреса группы не менять."""
    user = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if user is None or not any(
        address.id == address_id for address in list_managed_addresses(session, max_user_id)
    ):
        return False
    session.execute(
        update(users_chat)
        .where(users_chat.c.user_id == user.id, users_chat.c.address_id == address_id)
        .values(address_id=None)
    )
    if user.address_id == address_id:
        # Не оставляем удалённый адрес точкой отсчёта новостей. Если есть другой
        # выбранный дом, он становится личным адресом.
        user.address_id = session.scalar(
            select(users_chat.c.address_id)
            .join(ChatRow, ChatRow.chat_id == users_chat.c.chat_id)
            .where(
                users_chat.c.user_id == user.id,
                users_chat.c.address_id.is_not(None),
                ChatRow.chat_type == "chat",
            )
            .order_by(users_chat.c.chat_id)
            .limit(1)
        )
    session.flush()
    return True
