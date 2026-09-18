"""Бизнес-логика KAN-7; MAX/KAN-8 позже только вызывают эти handlers."""

from __future__ import annotations

import secrets

from sqlalchemy import update
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from address.handlers import resolve_home_address
from auth.db.user import UserRow
from auth.handlers.authorize import get_user_by_max_id
from chat_link.db import ChatLinkRow
from chat_link.models import AddressConnectResult, ChatLink, ChatLinkStatus
from user_chat.handlers import add_user_to_chat, create_chat, get_chat, list_chats_by_address
from user_chat.models import Chat, ChatCreate

_PENDING = {ChatLinkStatus.PENDING_BOT.value, ChatLinkStatus.PENDING_ADMIN.value}


def _to_domain(row: ChatLinkRow) -> ChatLink:
    return ChatLink(
        token=row.token,
        address_id=row.address_id,
        created_by_user_id=row.created_by_user_id,
        chat_id=row.chat_id,
        status=ChatLinkStatus(row.status),
        created_at=row.created_at,
    )


def get_chat_link(session: Session, token: str) -> ChatLink | None:
    row = session.get(ChatLinkRow, token)
    return _to_domain(row) if row is not None else None


def connect_to_chat(session: Session, *, max_user_id: int, chat_id: int) -> Chat:
    """MVP admin-approve mock: сразу зафиксировать membership в существующем чате."""
    chat = get_chat(session, chat_id)
    if chat is None:
        raise ValueError(f"Чат chat_id={chat_id} не найден")
    add_user_to_chat(session, chat_id, max_user_id=max_user_id)
    return chat


def connect_by_address(
    session: Session, *, max_user_id: int, user_input: str
) -> AddressConnectResult:
    """Разрешить адрес и подключить пользователя, если найден ровно один чат.

    Реальный approve администратора пока не вызывается: успешное добавление в
    `users_chat` и есть оговоренный для MVP auto-accept mock.
    """
    if get_user_by_max_id(session, max_user_id) is None:
        raise ValueError(f"Пользователь max_user_id={max_user_id} не зарегистрирован")

    address = resolve_home_address(session, user_input)
    if address.id is None:
        raise ValueError("У адреса отсутствует id")

    chats = list_chats_by_address(session, address.id)
    chat_ids = tuple(chat.chat_id for chat in chats)
    if len(chats) == 1:
        connect_to_chat(session, max_user_id=max_user_id, chat_id=chats[0].chat_id)
        return AddressConnectResult(
            address_id=address.id,
            address_text=address.address_text,
            chat_ids=chat_ids,
            joined_chat_id=chats[0].chat_id,
        )

    # 0 чатов -> следующий шаг спрашивает admin/non-admin.
    # >1 чата -> UI должен дать выбрать чат, а затем вызвать connect_to_chat().
    return AddressConnectResult(
        address_id=address.id,
        address_text=address.address_text,
        chat_ids=chat_ids,
    )


def create_chat_link(
    session: Session,
    *,
    address_id: int,
    max_user_id: int,
    is_admin: bool,
) -> ChatLink:
    """Создать следующий шаг flow после адреса, для которого ещё нет чата.

    `is_admin=True` означает «предложить добавить бота в свой чат».
    `False` — «передать токен администратору». Проверку роли позже делает MAX-слой.
    """
    if session.get(AddressRow, address_id) is None:
        raise ValueError(f"Адрес id={address_id} не найден")
    user = get_user_by_max_id(session, max_user_id)
    if user is None or user.id is None:
        raise ValueError(f"Пользователь max_user_id={max_user_id} не зарегистрирован")

    # У одного пользователя оставляем одну актуальную незавершённую заявку.
    session.execute(
        update(ChatLinkRow)
        .where(
            ChatLinkRow.created_by_user_id == user.id,
            ChatLinkRow.status.in_(_PENDING),
        )
        .values(status=ChatLinkStatus.CANCELLED.value)
    )

    token = secrets.token_urlsafe(12)
    while session.get(ChatLinkRow, token) is not None:
        token = secrets.token_urlsafe(12)
    status = ChatLinkStatus.PENDING_BOT if is_admin else ChatLinkStatus.PENDING_ADMIN
    row = ChatLinkRow(
        token=token,
        address_id=address_id,
        created_by_user_id=user.id,
        status=status.value,
    )
    session.add(row)
    session.flush()
    return _to_domain(row)


def bind_chat_link(
    session: Session,
    *,
    token: str,
    chat_id: int,
    title: str = "Чат соседей",
    invite_link: str | None = None,
) -> Chat:
    """Завершить заявку, когда внешний слой уже получил реальный MAX chat_id.

    Автор заявки сразу добавляется в membership: это mock положительного решения
    администратора из постановки KAN-7. Реальные уведомления/approve относятся к KAN-15.
    """
    row = session.get(ChatLinkRow, token)
    if row is None:
        raise ValueError("Код подключения не найден")
    if row.status not in _PENDING and not (
        row.status == ChatLinkStatus.READY.value and row.chat_id == chat_id
    ):
        raise ValueError("Код подключения уже недействителен")

    chat = get_chat(session, chat_id)
    if chat is None:
        chat = create_chat(
            session,
            ChatCreate(
                chat_id=chat_id,
                address_id=row.address_id,
                title=title or "Чат соседей",
                invite_link=invite_link,
            ),
        )
    elif chat.address_id != row.address_id:
        raise ValueError("Этот чат уже привязан к другому адресу")

    creator = session.get(UserRow, row.created_by_user_id)
    if creator is None:
        raise ValueError("Автор заявки больше не существует")
    add_user_to_chat(session, chat_id, max_user_id=creator.max_user_id)
    row.chat_id = chat_id
    row.status = ChatLinkStatus.READY.value
    session.flush()
    return chat


def connect_by_token(session: Session, *, token: str, max_user_id: int) -> Chat:
    """Backend для будущей referral/deep-link: auto-accept в готовый чат."""
    row = session.get(ChatLinkRow, token)
    if row is None:
        raise ValueError("Код приглашения не найден")
    if row.status != ChatLinkStatus.READY.value or row.chat_id is None:
        raise ValueError("Чат по этому коду ещё не подключён")
    return connect_to_chat(session, max_user_id=max_user_id, chat_id=row.chat_id)
