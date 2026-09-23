from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.db import UserRow
from chat_link.db import ChatLinkRow
from chat_link.models import ChatLink, ChatLinkStatus
from user_chat.handlers import (
    add_user_to_chat,
    create_chat,
    get_chat,
    list_chats_by_address,
    promote_chat_to_group,
)
from user_chat.models import Chat, ChatCreate


def _domain(row: ChatLinkRow) -> ChatLink:
    return ChatLink(
        id=row.id,
        token=row.token,
        requester_user_id=row.requester_user_id,
        address_id=row.address_id,
        status=ChatLinkStatus(row.status),
        chat_id=row.chat_id,
        admin_user_id=row.admin_user_id,
    )


def _row_by_token(session: Session, token: str) -> ChatLinkRow | None:
    return session.scalar(select(ChatLinkRow).where(ChatLinkRow.token == token))


def create_request(
    session: Session,
    *,
    max_user_id: int,
    address_id: int,
) -> tuple[ChatLink, list[Chat]]:
    user = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if user is None:
        raise ValueError("Пользователь не зарегистрирован")

    active = session.scalars(
        select(ChatLinkRow).where(
            ChatLinkRow.requester_user_id == user.id,
            ChatLinkRow.status.in_(
                [
                    ChatLinkStatus.WAITING_GROUP.value,
                    ChatLinkStatus.WAITING_JOIN.value,
                    ChatLinkStatus.WAITING_APPROVAL.value,
                    ChatLinkStatus.APPROVAL_SENT.value,
                ]
            ),
        )
    )
    for previous in active:
        previous.status = ChatLinkStatus.CANCELLED.value

    chats = list_chats_by_address(session, address_id)
    status = ChatLinkStatus.WAITING_JOIN if chats else ChatLinkStatus.WAITING_GROUP
    row = ChatLinkRow(
        token=secrets.token_urlsafe(12)[:16],
        requester_user_id=user.id,
        address_id=address_id,
        status=status.value,
    )
    session.add(row)
    session.flush()
    return _domain(row), chats


def get_request_by_token(session: Session, token: str) -> ChatLink | None:
    row = _row_by_token(session, token)
    return _domain(row) if row is not None else None


def mark_waiting_group(session: Session, *, token: str) -> None:
    """Перевести заявку в создание группы, если DB-чаты оказались legacy DIALOG."""
    row = _row_by_token(session, token)
    if row is None:
        raise ValueError("Заявка не найдена")
    if row.status == ChatLinkStatus.WAITING_JOIN.value:
        row.status = ChatLinkStatus.WAITING_GROUP.value
        session.flush()


def claim_admin_request(session: Session, *, token: str, max_user_id: int) -> ChatLink:
    """Запомнить админа, который открыл пересланный capability deep-link."""
    row = _row_by_token(session, token)
    if row is None or row.status != ChatLinkStatus.WAITING_GROUP.value:
        raise ValueError("Заявка не найдена или уже завершена")
    admin = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if admin is None:
        raise ValueError("Пользователь не зарегистрирован")
    previous_claims = session.scalars(
        select(ChatLinkRow).where(
            ChatLinkRow.status == ChatLinkStatus.WAITING_GROUP.value,
            ChatLinkRow.admin_user_id == admin.id,
            ChatLinkRow.id != row.id,
        )
    )
    for previous in previous_claims:
        previous.admin_user_id = None
    row.admin_user_id = admin.id
    session.flush()
    return _domain(row)


def pending_for_actor(session: Session, max_user_id: int) -> ChatLink | None:
    """Одна активная заявка, которую пользователь сейчас подключает как админ.

    Явно забранная через admin deep-link заявка имеет приоритет над собственной.
    `create_request` уже отменяет старые заявки инициатора, поэтому собственная
    WAITING_GROUP-заявка у пользователя может быть только одна.
    """
    user = session.scalar(select(UserRow).where(UserRow.max_user_id == max_user_id))
    if user is None:
        return None

    claimed = session.scalar(
        select(ChatLinkRow)
        .where(
            ChatLinkRow.status == ChatLinkStatus.WAITING_GROUP.value,
            ChatLinkRow.admin_user_id == user.id,
        )
        .order_by(ChatLinkRow.created_at.desc())
        .limit(1)
    )
    if claimed is not None:
        return _domain(claimed)

    own = session.scalar(
        select(ChatLinkRow)
        .where(
            ChatLinkRow.status == ChatLinkStatus.WAITING_GROUP.value,
            ChatLinkRow.requester_user_id == user.id,
        )
        .order_by(ChatLinkRow.created_at.desc())
        .limit(1)
    )
    return _domain(own) if own is not None else None


def finalize_group(
    session: Session,
    *,
    token: str,
    chat_id: int,
    title: str,
    invite_link: str | None,
    admin_max_user_id: int,
) -> int | None:
    """Привязать реальный MAX-чат к дому и вернуть MAX id инициатора заявки."""
    row = _row_by_token(session, token)
    if row is None or row.status not in {
        ChatLinkStatus.WAITING_GROUP.value,
        ChatLinkStatus.WAITING_JOIN.value,
    }:
        raise ValueError("Заявка не найдена или уже завершена")

    existing = get_chat(session, chat_id)
    if existing is None:
        create_chat(
            session,
            ChatCreate(
                chat_id=chat_id,
                address_id=row.address_id,
                title=title or "Чат соседей",
                invite_link=invite_link,
            ),
        )
    elif existing.address_id != row.address_id:
        raise ValueError("Этот MAX-чат уже привязан к другому адресу")
    elif existing.chat_type != "chat":
        promote_chat_to_group(
            session,
            chat_id,
            title=title or existing.title,
            invite_link=invite_link,
        )

    admin = session.scalar(select(UserRow).where(UserRow.max_user_id == admin_max_user_id))
    requester = session.get(UserRow, row.requester_user_id)
    if admin is None or requester is None:
        raise ValueError("Пользователь не зарегистрирован")

    add_user_to_chat(session, chat_id, max_user_id=admin_max_user_id)
    row.admin_user_id = admin.id
    row.chat_id = chat_id
    # Если админ и есть инициатор, он уже точно состоит в групповом чате.
    if requester.max_user_id == admin_max_user_id:
        row.status = ChatLinkStatus.CONNECTED.value
    else:
        row.status = ChatLinkStatus.WAITING_JOIN.value
    session.flush()
    return requester.max_user_id


def mark_joined(session: Session, *, token: str, chat_id: int) -> None:
    row = _row_by_token(session, token)
    if row is None:
        raise ValueError("Заявка не найдена")
    chat = get_chat(session, chat_id)
    if chat is None or chat.address_id != row.address_id:
        raise ValueError("Чат не соответствует выбранному адресу")
    requester = session.get(UserRow, row.requester_user_id)
    if requester is None:
        raise ValueError("Пользователь не зарегистрирован")
    add_user_to_chat(session, chat_id, max_user_id=requester.max_user_id)
    row.chat_id = chat_id
    row.status = ChatLinkStatus.CONNECTED.value
    session.flush()
