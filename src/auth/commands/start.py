"""Команды Max: тонкая обёртка над handlers."""

from __future__ import annotations

from typing import Any

from maxapi.filters.command import CommandStart

from auth.commands.webapp_keyboard import build_webapp_keyboard
from auth.handlers.authorize import authorize_from_event


def _welcome_text(name: str, *, returning: bool) -> str:
    if returning:
        return f"Снова привет, {name}!\n\nОткрой ленту новостей района — кнопка ниже."
    return (
        f"Привет, {name}! Вы авторизованы.\n\n"
        "Нажми кнопку, чтобы открыть мини-приложение «Умный город»."
    )


def register_auth_commands(dp: Any, bot: Any) -> None:
    """Подключить команды авторизации к Dispatcher."""

    @dp.bot_started()
    async def on_bot_started(event: Any) -> None:
        user = authorize_from_event(event)
        if user is None:
            return

        name = user.name or user.username or "друг"
        keyboard = await build_webapp_keyboard(bot)
        await bot.send_message(
            chat_id=event.chat_id,
            text=_welcome_text(name, returning=False),
            attachments=[keyboard],
        )

    @dp.message_created(CommandStart())
    async def on_start(event: Any) -> None:
        user = authorize_from_event(event)
        if user is None:
            return

        name = user.name or user.username or "друг"
        keyboard = await build_webapp_keyboard(bot)
        await event.message.answer(
            text=_welcome_text(name, returning=True),
            attachments=[keyboard],
        )
