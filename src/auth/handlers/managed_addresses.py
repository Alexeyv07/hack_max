"""Личные адреса, которые пользователь выбрал в подключённых домовых чатах."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from auth.db.user import UserRow
from user_chat.db import ChatRow, user_chat_addresses, users_chat
from user_chat.handlers.membership import linked_group_ids


@dataclass(frozen=True, slots=True)
class ManagedAddress:
    id: int
    text: str
    chat_titles: tuple[str, ...] = ()


def list_managed_addresses(session: Session, max_user_id: int) -> list[ManagedAddress]:
    """Только собственные подтверждённые адреса, не все дома общих чатов."""
    user = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if user is None:
        return []

    rows = session.execute(
        select(AddressRow.id, AddressRow.address_text, ChatRow.title)
        .join(users_chat, users_chat.c.address_id == AddressRow.id)
        .join(ChatRow, ChatRow.chat_id == users_chat.c.chat_id)
        .where(users_chat.c.user_id == user.id, ChatRow.chat_type == "chat")
        .order_by(AddressRow.address_text, AddressRow.id, ChatRow.title)
    ).all()

    # Переход по групповой ссылке сохраняет сразу все адреса чата; при этом
    # users_chat.address_id остаётся единственным явно выбранным домом.
    referral_rows = session.execute(
        select(AddressRow.id, AddressRow.address_text, ChatRow.title)
        .join(user_chat_addresses, user_chat_addresses.c.address_id == AddressRow.id)
        .join(ChatRow, ChatRow.chat_id == user_chat_addresses.c.chat_id)
        .where(
            user_chat_addresses.c.user_id == user.id,
            ChatRow.chat_type == "chat",
        )
        .order_by(AddressRow.address_text, AddressRow.id, ChatRow.title)
    ).all()

    addresses: dict[int, str] = {}
    chats_by_address: dict[int, set[str]] = {}
    for address_id, text, chat_title in [*rows, *referral_rows]:
        addresses[address_id] = text
        chats_by_address.setdefault(address_id, set()).add(chat_title)

    # Личный адрес может отличаться от выбранных адресов в других группах.
    if user.address_id is not None and user.address_id not in addresses:
        group_ids = linked_group_ids(session, max_user_id, address_id=user.address_id)
        if group_ids:
            personal = session.get(AddressRow, user.address_id)
            if personal is not None:
                addresses[personal.id] = personal.address_text
                chats_by_address[personal.id] = set(
                    session.scalars(select(ChatRow.title).where(ChatRow.chat_id.in_(group_ids)))
                )

    return [
        ManagedAddress(id_, text, tuple(sorted(chats_by_address.get(id_, ()))))
        for id_, text in sorted(addresses.items(), key=lambda x: (x[1], x[0]))
    ]


def list_managed_address_rows(session: Session, max_user_id: int) -> list[AddressRow]:
    """Все адреса из «Мои адреса» в порядке их первого сохранения.

    Для старых строк до 0027 порядок добавления восстановить нельзя, поэтому
    они идут после адресов с известным временем в стабильном порядке списка.
    """
    managed = list_managed_addresses(session, max_user_id)
    if not managed:
        return []
    user = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if user is None:
        return []

    ids = [item.id for item in managed]
    fallback_position = {address_id: index for index, address_id in enumerate(ids)}
    first_added = dict(
        session.execute(
            select(
                user_chat_addresses.c.address_id,
                func.min(user_chat_addresses.c.added_at),
            )
            .where(
                user_chat_addresses.c.user_id == user.id,
                user_chat_addresses.c.address_id.in_(ids),
            )
            .group_by(user_chat_addresses.c.address_id)
        ).all()
    )

    def sort_key(address_id: int):
        added_at = first_added.get(address_id)
        if added_at is not None:
            return (0, added_at, address_id)
        return (1, fallback_position[address_id], address_id)

    rows = {
        row.id: row
        for row in session.scalars(select(AddressRow).where(AddressRow.id.in_(ids))).all()
    }
    return [rows[address_id] for address_id in sorted(ids, key=sort_key) if address_id in rows]


def remove_managed_address(session: Session, *, max_user_id: int, address_id: int) -> bool:
    """Убрать адрес только у пользователя. Членство и адреса группы не менять."""
    user = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if user is None or not any(
        address.id == address_id for address in list_managed_addresses(session, max_user_id)
    ):
        return False
    session.execute(
        delete(user_chat_addresses).where(
            user_chat_addresses.c.user_id == user.id,
            user_chat_addresses.c.address_id == address_id,
        )
    )
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
