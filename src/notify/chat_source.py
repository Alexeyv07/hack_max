"""Хранилище обычных текстов домовых чатов для ежедневной суммаризации.

KAN-10 сохраняет в events лишь отфильтрованные события. Здесь хранятся
сообщения для #итого отдельно, без текста от ботов и MAX-команд.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from notify.db import NotifyChatMessageRow
from project.database import get_session_factory

if TYPE_CHECKING:
    from parse_chat.models.message import RawChatMessage


@dataclass(frozen=True, slots=True)
class ChatMessage:
    text: str
    created_at: datetime
    row_id: int | None = None


ChatMessageLoader = Callable[[int, datetime | None], Awaitable[Sequence[ChatMessage]]]


def persist_digest_message(session: Session, message: RawChatMessage) -> bool:
    """Идемпотентно сохранить содержательное сообщение уже подключённого чата."""
    text = " ".join(message.text.split())
    if message.sender_is_bot or not text or text.startswith("/") or not message.message_id:
        return False

    # Один и тот же update MAX может прийти повторно при reconnect.
    existing = session.scalar(
        select(NotifyChatMessageRow.id).where(
            NotifyChatMessageRow.chat_id == message.chat_id,
            NotifyChatMessageRow.message_id == message.message_id,
        )
    )
    if existing is not None:
        return False

    try:
        with session.begin_nested():
            session.add(
                NotifyChatMessageRow(
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    text=text[:4000],
                    created_at=message.published_at or datetime.now(UTC),
                )
            )
            session.flush()
    except IntegrityError:
        return False
    return True


async def load_chat_messages(
    chat_id: int, after: datetime | None, *, after_id: int | None = None
) -> Sequence[ChatMessage]:
    """Вернуть тексты одного чата после курсора предыдущего успешного дайджеста."""
    with get_session_factory()() as session:
        query = select(NotifyChatMessageRow).where(NotifyChatMessageRow.chat_id == chat_id)
        if after_id is not None:
            query = query.where(NotifyChatMessageRow.id > after_id)
        elif after is not None:
            # Совместимость с cursor из версии до появления ID сообщений.
            query = query.where(NotifyChatMessageRow.created_at > after)
        rows = session.scalars(query.order_by(NotifyChatMessageRow.id)).all()
        return [
            ChatMessage(text=row.text, created_at=row.created_at, row_id=row.id) for row in rows
        ]
