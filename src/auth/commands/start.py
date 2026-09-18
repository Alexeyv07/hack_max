"""Команды Max: авторизация и первый экран бота."""

from __future__ import annotations

from html import escape
from typing import Any

from maxapi import F
from maxapi.enums.format import Format
from maxapi.filters.command import CommandStart
from maxapi.types import CallbackButton, OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from auth.handlers.authorize import authorize_from_event

DOCS_URL = "https://alexeyv07.github.io/hack_max/"
CHAT_LINK_START_PAYLOAD = "chat_link:start"
CHAT_LINK_MOCK_NOTIFICATION = "Подключение чата скоро появится."


def build_welcome_text(name: str) -> str:
    """Текст первого экрана."""
    safe_name = escape(name)

    return (
        f"Привет, {safe_name}! Я помогу следить за важными событиями "
        "рядом с вашим домом и в районе.\n\n"
        f'🔗 <a href="{DOCS_URL}"><b>Подробнее о проекте</b></a>'
    )


def build_welcome_keyboard(bot: Any) -> Any:
    """Две кнопки первого экрана."""
    me = getattr(bot, "me", None)
    username = getattr(me, "username", None)
    user_id = getattr(me, "user_id", None)

    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        CallbackButton(
            text="Добавить чат",
            payload=CHAT_LINK_START_PAYLOAD,
        ),
        OpenAppButton(
            text="Смотреть события",
            web_app=username,
            contact_id=user_id,
        ),
    )

    return keyboard.as_markup()


def _display_name(user: Any) -> str:
    return user.name or user.username or "друг"


def register_auth_commands(dp: Any, bot: Any) -> None:
    """Подключить команды авторизации и приветственный экран."""

    @dp.bot_started()
    async def on_bot_started(event: Any) -> None:
        user = authorize_from_event(event)
        if user is None:
            return

        await bot.send_message(
            chat_id=event.chat_id,
            text=build_welcome_text(_display_name(user)),
            attachments=[build_welcome_keyboard(bot)],
            format=Format.HTML,
        )

    @dp.message_created(CommandStart())
    async def on_start(event: Any) -> None:
        user = authorize_from_event(event)
        if user is None:
            return

        await event.message.answer(
            text=build_welcome_text(_display_name(user)),
            attachments=[build_welcome_keyboard(bot)],
            format=Format.HTML,
        )

    @dp.message_callback(F.callback.payload == CHAT_LINK_START_PAYLOAD)
    async def on_add_chat_mock(event: Any) -> None:
        # KAN-7 заменит этот mock на реальный chat_link flow.
        await event.answer(notification=CHAT_LINK_MOCK_NOTIFICATION)
