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


def is_private_chat_event(event: Any) -> bool:
    """Не запускать команды личного бота из MAX-группы или канала.

    В message_created тип находится в message.recipient.chat_type; у bot_started
    он доступен через event.chat.type. Для старых событий без типа используем
    chat_id: у групп MAX он отрицательный.
    """
    message = getattr(event, "message", None)
    recipient = getattr(message, "recipient", None)
    chat_type = getattr(recipient, "chat_type", None)
    if chat_type is None:
        chat_type = getattr(getattr(event, "chat", None), "type", None)
    if chat_type is not None:
        return str(getattr(chat_type, "value", chat_type)).lower() == "dialog"
    if getattr(event, "is_channel", False):
        return False
    chat_id = extract_chat_id(event)
    return chat_id is None or chat_id > 0
