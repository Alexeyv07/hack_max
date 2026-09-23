"""Сырое сообщение соседского чата до фильтров / persist."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawChatMessage:
    """Сообщение из Max message_created (после извлечения полей)."""

    chat_id: int
    message_id: str
    text: str
    sender_user_id: int | None
    sender_is_bot: bool
    published_at: datetime | None
    has_attachments: bool = False
    image_url: str | None = None
    # Прямая ссылка на сообщение в MAX (message.url / build_message_link).
    source_url: str | None = None
