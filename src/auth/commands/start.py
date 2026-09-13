"""Команды и обработчики событий Max, связанные с авторизацией."""

from __future__ import annotations

from typing import Any

from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload
from project.database import session_scope
from project.logging_setup import get_logger

logger = get_logger(__name__)


def _extract_chat_id(event: Any) -> int | None:
    chat_id = getattr(event, "chat_id", None)
    if chat_id is not None:
        return chat_id
    message = getattr(event, "message", None)
    if message is None:
        return None
    recipient = getattr(message, "recipient", None)
    return getattr(recipient, "chat_id", None) if recipient else None


def _extract_sender(event: Any) -> Any | None:
    message = getattr(event, "message", None)
    if message is not None:
        sender = getattr(message, "sender", None) or getattr(message, "user", None)
        if sender is not None:
            return sender
    return getattr(event, "user", None)


def register_auth_commands(dp: Any, bot: Any) -> None:
    """
    Подключить обработчики авторизации к Dispatcher maxapi.

    Обрабатывает:
      - bot_started  — пользователь нажал «Начать» / открыл по диплинку
      - /start       — явная команда старта
    """

    @dp.bot_started()
    async def on_bot_started(event: Any) -> None:
        user_payload = MaxUserPayload.from_event_user(
            event.user,
            chat_id=getattr(event, "chat_id", None),
            payload=getattr(event, "payload", None),
        )
        with session_scope() as session:
            user = authorize_user(session, user_payload)

        greeting_name = user.name or user.username or "друг"
        await bot.send_message(
            chat_id=event.chat_id,
            text=f"Привет, {greeting_name}! Вы авторизованы.",
        )
        logger.debug("Обработан bot_started для max_user_id=%s", user.max_user_id)

    # Предпочитаем фильтр Command из maxapi; иначе — проверка текста.
    try:
        from maxapi.filters.command import Command

        start_filter: Any = Command("start")
    except ImportError:  # pragma: no cover
        try:
            from maxapi import Command

            start_filter = Command("start")
        except ImportError:
            start_filter = None

    if start_filter is not None:

        @dp.message_created(start_filter)
        async def on_start_command(event: Any) -> None:
            await _authorize_from_message(event, bot)
    else:

        @dp.message_created()
        async def on_start_command_fallback(event: Any) -> None:
            message = getattr(event, "message", None)
            body = getattr(message, "body", None) if message else None
            text = (getattr(body, "text", None) or "").strip() if body else ""
            if text.startswith("/start"):
                await _authorize_from_message(event, bot)


async def _authorize_from_message(event: Any, bot: Any) -> None:
    sender = _extract_sender(event)
    if sender is None:
        logger.warning("Нельзя авторизовать /start: в событии нет отправителя")
        return

    chat_id = _extract_chat_id(event)
    user_payload = MaxUserPayload.from_event_user(sender, chat_id=chat_id)
    with session_scope() as session:
        user = authorize_user(session, user_payload)

    greeting_name = user.name or user.username or "друг"
    text = f"Снова привет, {greeting_name}!"
    message = getattr(event, "message", None)
    if message is not None and hasattr(message, "answer"):
        await message.answer(text)
    elif chat_id is not None:
        await bot.send_message(chat_id=chat_id, text=text)
