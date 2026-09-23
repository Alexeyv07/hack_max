"""Авторизация / upsert пользователей Max в PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.db.user import UserRow
from auth.models.user import MaxUserPayload, User
from project.database import session_scope
from project.logging_setup import get_logger
from project.max_events import extract_chat_id, extract_sender

logger = get_logger(__name__)


def _to_domain(row: UserRow) -> User:
    return User(
        id=row.id,
        max_user_id=row.max_user_id,
        name=row.name,
        username=row.username,
        chat_id=row.chat_id,
        start_payload=row.start_payload,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_seen_at=row.last_seen_at,
    )


def get_user_by_max_id(session: Session, max_user_id: int) -> User | None:
    """Найти пользователя по id в Max."""
    stmt = select(UserRow).where(UserRow.max_user_id == max_user_id)
    row = session.scalars(stmt).first()
    return _to_domain(row) if row else None


def authorize_user(session: Session, payload: MaxUserPayload) -> User:
    """
    Создать или обновить пользователя при входе в бота.

    При первом визите — insert; при повторных — обновление профиля и last_seen_at.
    """
    now = datetime.now(UTC)
    stmt = select(UserRow).where(UserRow.max_user_id == payload.max_user_id)
    row = session.scalars(stmt).first()

    if row is None:
        row = UserRow(
            max_user_id=payload.max_user_id,
            name=payload.name,
            username=payload.username,
            chat_id=payload.chat_id,
            start_payload=payload.payload,
            last_seen_at=now,
        )
        session.add(row)
        session.flush()
        logger.info(
            "Новый пользователь авторизован max_user_id=%s username=%s chat_id=%s",
            payload.max_user_id,
            payload.username,
            payload.chat_id,
        )
    else:
        row.name = payload.name or row.name
        row.username = payload.username or row.username
        if payload.chat_id is not None:
            row.chat_id = payload.chat_id
        if payload.payload is not None:
            row.start_payload = payload.payload
        row.last_seen_at = now
        session.flush()
        logger.info(
            "Пользователь обновлён max_user_id=%s username=%s",
            payload.max_user_id,
            payload.username,
        )

    return _to_domain(row)


def authorize_from_event(event: Any) -> User | None:
    """Достать пользователя из события Max и сохранить/обновить в БД."""
    sender = extract_sender(event)
    if sender is None:
        logger.warning("В событии нет отправителя — авторизация пропущена")
        return None

    payload = MaxUserPayload.from_event_user(
        sender,
        chat_id=extract_chat_id(event),
        payload=getattr(event, "payload", None),
    )
    with session_scope() as session:
        user = authorize_user(session, payload)
        # Только новое обращение в личном диалоге даёт основание повторить доставку.
        # Групповой /start (отрицательный chat_id) не снимает блокировку.
        if payload.chat_id is not None and payload.chat_id > 0:
            row = session.get(UserRow, user.id)
            if row is not None and row.notify_blocked_at is not None:
                row.notify_blocked_at = None
                row.notify_blocked_reason = None
                session.flush()
                logger.info(
                    "Повторно разрешены личные уведомления max_user_id=%s", user.max_user_id
                )
        return user
