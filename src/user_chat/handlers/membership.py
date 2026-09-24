"""Членство пользователя в чатах соседей."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from auth.db.user import UserRow
from auth.handlers.authorize import get_user_by_max_id
from project.config import get_settings
from user_chat.db import ChatRow, chat_addresses, users_chat
from user_chat.models.chat import ChatMember
from user_chat.models.membership import ChatMembership


def add_user_to_chat(session: Session, chat_id: int, *, max_user_id: int) -> bool:
    """Добавить зарегистрированного пользователя; False, если он уже состоит в чате."""
    chat = session.get(ChatRow, chat_id)
    if chat is None:
        raise ValueError(f"Чат chat_id={chat_id} не найден")
    user = get_user_by_max_id(session, max_user_id)
    if user is None:
        raise ValueError(f"Пользователь max_user_id={max_user_id} не зарегистрирован")
    # PostgreSQL в приложении, SQLite в тестах. ON CONFLICT защищает и от гонки
    # двух одновременных добавлений, не откатывая остальные изменения транзакции.
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    result = session.execute(
        insert(users_chat)
        .values(user_id=user.id, chat_id=chat_id)
        .on_conflict_do_nothing(index_elements=["user_id", "chat_id"])
    )
    session.expire(chat, ["users"])
    return result.rowcount == 1


def set_member_address(
    session: Session, chat_id: int, *, max_user_id: int, address_id: int
) -> None:
    """Запомнить личный дом участника, только из адресов его подключённого чата."""
    user = get_user_by_max_id(session, max_user_id)
    chat = session.get(ChatRow, chat_id)
    if user is None or chat is None or chat.chat_type != "chat":
        raise ValueError("Домовой чат не подключён")
    allowed = session.scalar(
        select(chat_addresses.c.address_id).where(
            chat_addresses.c.chat_id == chat_id, chat_addresses.c.address_id == address_id
        )
    )
    if allowed is None:
        raise ValueError(
            "Этого адреса нет среди домов чата. Попросите администратора добавить его."
        )
    membership = session.execute(
        select(users_chat.c.user_id).where(
            users_chat.c.chat_id == chat_id, users_chat.c.user_id == user.id
        )
    ).first()
    if membership is None:
        raise ValueError("Сначала вступите в групповой чат")
    session.execute(
        users_chat.update()
        .where(users_chat.c.chat_id == chat_id, users_chat.c.user_id == user.id)
        .values(address_id=address_id)
    )
    session.flush()


def remove_user_from_chat(session: Session, chat_id: int, *, max_user_id: int) -> bool:
    """Удалить только членство; False, если чата, пользователя или связи нет."""
    chat = session.get(ChatRow, chat_id)
    user = get_user_by_max_id(session, max_user_id)
    if chat is None or user is None:
        return False
    result = session.execute(
        delete(users_chat).where(users_chat.c.chat_id == chat_id, users_chat.c.user_id == user.id)
    )
    session.expire(chat, ["users"])
    return result.rowcount == 1


def list_chat_members(session: Session, chat_id: int) -> list[ChatMember]:
    """Участники конкретного чата; для пустого или неизвестного чата — []."""
    rows = session.scalars(
        select(UserRow)
        .join(users_chat, users_chat.c.user_id == UserRow.id)
        .where(users_chat.c.chat_id == chat_id)
        .order_by(UserRow.id)
    )
    return [
        ChatMember(
            user_id=row.id, max_user_id=row.max_user_id, name=row.name, username=row.username
        )
        for row in rows
    ]


def list_memberships_for_user(session: Session, max_user_id: int) -> list[ChatMembership]:
    """Координаты собственного выбранного дома, а не первого адреса дворового чата."""
    rows = session.execute(
        select(
            ChatRow,
            AddressRow.id,
            AddressRow.latitude,
            AddressRow.longitude,
            AddressRow.street,
            AddressRow.house,
        )
        .join(users_chat, users_chat.c.chat_id == ChatRow.chat_id)
        .join(UserRow, UserRow.id == users_chat.c.user_id)
        .join(AddressRow, AddressRow.id == users_chat.c.address_id)
        .where(UserRow.max_user_id == max_user_id, ChatRow.chat_type == "chat")
        .order_by(ChatRow.chat_id)
    )
    settings = get_settings()
    return [
        ChatMembership(
            chat_id=chat.chat_id,
            address_id=address_id,
            title=chat.title,
            lat=float(lat),
            lon=float(lon),
            nearby_radius_m=settings.events.nearby_radius_m,
            city_radius_m=settings.events.city_radius_m,
            street=street,
            house=house,
        )
        for chat, address_id, lat, lon, street, house in rows
    ]


def linked_group_ids(
    session: Session, max_user_id: int, *, address_id: int | None = None
) -> list[int]:
    """Подтверждённые в БД участники групп, к которым привязан хотя бы один дом.

    Личный адрес ещё может быть не выбран: users_chat.address_id тогда NULL.
    """
    stmt = (
        select(ChatRow.chat_id)
        .join(users_chat, users_chat.c.chat_id == ChatRow.chat_id)
        .join(UserRow, UserRow.id == users_chat.c.user_id)
        .join(chat_addresses, chat_addresses.c.chat_id == ChatRow.chat_id)
        .where(UserRow.max_user_id == max_user_id, ChatRow.chat_type == "chat")
        .distinct()
        .order_by(ChatRow.chat_id)
    )
    if address_id is not None:
        stmt = stmt.where(chat_addresses.c.address_id == address_id)
    return list(session.scalars(stmt))


def has_linked_group(session: Session, max_user_id: int) -> bool:
    """Член группы с адресами, даже если собственный дом ещё не выбран."""
    return bool(linked_group_ids(session, max_user_id))


def has_connected_chat(session: Session, max_user_id: int) -> bool:
    """Есть ли у пользователя хотя бы один подключённый домовой чат."""
    user_id = session.scalar(select(UserRow.id).where(UserRow.max_user_id == max_user_id))
    if user_id is None:
        return False
    return (
        session.scalar(
            select(users_chat.c.user_id)
            .join(ChatRow, ChatRow.chat_id == users_chat.c.chat_id)
            .where(
                users_chat.c.user_id == user_id,
                users_chat.c.address_id.is_not(None),
                ChatRow.chat_type == "chat",
            )
            .limit(1)
        )
        is not None
    )


def bind_known_chat_member(session: Session, chat_id: int, *, max_user_id: int) -> bool:
    """Сохранить membership после внешнего подтверждения, что пользователь уже в MAX-чате."""
    chat = session.get(ChatRow, chat_id)
    if chat is None or chat.chat_type != "chat":
        raise ValueError("Домовой чат не зарегистрирован")
    return add_user_to_chat(session, chat_id, max_user_id=max_user_id)
