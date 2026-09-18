"""Тесты клавиатуры open_app для приветствия."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from auth.commands.webapp_keyboard import (
    WEBAPP_BUTTON_TEXT,
    build_webapp_keyboard,
    resolve_bot_identity,
)


def test_resolve_bot_identity_from_me() -> None:
    bot = SimpleNamespace(me=SimpleNamespace(username="smartcity_bot", user_id=42))
    username, user_id = asyncio.run(resolve_bot_identity(bot))
    assert username == "smartcity_bot"
    assert user_id == 42


def test_build_webapp_keyboard_open_app() -> None:
    bot = SimpleNamespace(me=SimpleNamespace(username="demo_bot", user_id=99))
    markup = asyncio.run(build_webapp_keyboard(bot))

    assert (
        markup.type == "inline_keyboard" or getattr(markup.type, "value", None) == "inline_keyboard"
    )
    buttons = markup.payload.buttons
    assert len(buttons) == 1 and len(buttons[0]) == 1
    btn = buttons[0][0]
    assert btn.type.value == "open_app"
    assert btn.text == WEBAPP_BUTTON_TEXT
    assert btn.web_app == "demo_bot"
    assert btn.contact_id == 99
