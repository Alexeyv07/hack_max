"""Общие хелперы для разбора событий Max Bot API."""

from __future__ import annotations

from typing import Any


def extract_chat_id(event: Any) -> int | None:
    """Достать chat_id из update (bot_started, message_created и т.п.)."""
    chat_id = getattr(event, "chat_id", None)
    if chat_id is not None:
        return int(chat_id)

    chat = getattr(event, "chat", None)
    if chat is not None:
        nested = getattr(chat, "chat_id", None)
        if nested is not None:
            return int(nested)

    message = getattr(event, "message", None)
    if message is None:
        return None
    recipient = getattr(message, "recipient", None)
    if recipient is None:
        return None
    nested = getattr(recipient, "chat_id", None)
    return int(nested) if nested is not None else None


def extract_sender(event: Any) -> Any | None:
    """Достать пользователя-инициатора события."""
    from_user = getattr(event, "from_user", None)
    if from_user is not None:
        return from_user

    user = getattr(event, "user", None)
    if user is not None:
        return user

    message = getattr(event, "message", None)
    if message is None:
        return None
    return getattr(message, "sender", None)
