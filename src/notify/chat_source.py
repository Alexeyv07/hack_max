"""Тонкий интерфейс к сообщениям домовых чатов из будущего ``parse_chat``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from project.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Минимум данных, который notify получает от хранилища ``parse_chat``."""

    text: str
    created_at: datetime


ChatMessageLoader = Callable[[int, datetime | None], Awaitable[Sequence[ChatMessage]]]


async def load_chat_messages(chat_id: int, after: datetime | None) -> Sequence[ChatMessage]:
    """Заглушка адаптера до подключения таблицы сообщений ``parse_chat``.

    KAN-15 не создаёт своё хранилище сообщений. Когда KAN-10 предоставит таблицу,
    здесь останется только запрос к ней с фильтром ``created_at > after``.
    """
    logger.debug(
        "Источник сообщений parse_chat ещё не подключён: chat_id=%s after=%s",
        chat_id,
        after,
    )
    return []
