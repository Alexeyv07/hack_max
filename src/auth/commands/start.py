"""Команды Max: тонкая обёртка над handlers."""

from __future__ import annotations

from typing import Any

from maxapi.filters.command import CommandStart

from auth.handlers.authorize import authorize_from_event


def register_auth_commands(dp: Any, bot: Any) -> None:
    """Подключить команды авторизации к Dispatcher."""

    @dp.bot_started()
    async def on_bot_started(event: Any) -> None:
        user = authorize_from_event(event)
        if user is None:
            return

        name = user.name or user.username or "друг"
        await bot.send_message(
            chat_id=event.chat_id,
            text=f"Привет, {name}! Вы авторизованы.",
        )

    @dp.message_created(CommandStart())
    async def on_start(event: Any) -> None:
        user = authorize_from_event(event)
        if user is None:
            return

        name = user.name or user.username or "друг"
        await event.message.answer(f"Снова привет, {name}!")
