"""Inline-клавиатура: кнопка открытия мини-приложения (Max open_app)."""

from __future__ import annotations

from typing import Any

from maxapi.types import OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

WEBAPP_BUTTON_TEXT = "Открыть новости"


async def resolve_bot_identity(bot: Any) -> tuple[str | None, int | None]:
    """username и user_id текущего бота (для OpenAppButton)."""
    me = getattr(bot, "me", None)
    if me is None and hasattr(bot, "get_me"):
        me = await bot.get_me()
    if me is None:
        return None, None
    username = getattr(me, "username", None)
    user_id = getattr(me, "user_id", None)
    return (str(username) if username else None), (int(user_id) if user_id else None)


async def build_webapp_keyboard(bot: Any) -> Any:
    """
    Клавиатура с одной кнопкой open_app.

    Мини-приложение должно быть привязано к боту на платформе MAX
    (https → URL в настройках бота). См. https://dev.max.ru/docs/webapps/introduction
    и OpenAppButton в maxapi.
    """
    username, contact_id = await resolve_bot_identity(bot)

    builder = InlineKeyboardBuilder()
    builder.row(
        OpenAppButton(
            text=WEBAPP_BUTTON_TEXT,
            web_app=username,
            contact_id=contact_id,
        )
    )
    return builder.as_markup()
