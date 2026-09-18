"""KAN-8: приветственный экран Max-бота."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import auth.commands.start as start


class FakeDispatcher:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def _decorator(self, name: str):
        def register(func):
            self.handlers[name] = func
            return func

        return register

    def bot_started(self, *args, **kwargs):
        return self._decorator("bot_started")

    def message_created(self, *args, **kwargs):
        return self._decorator("message_created")

    def message_callback(self, *args, **kwargs):
        return self._decorator("message_callback")


def _bot():
    return SimpleNamespace(
        me=SimpleNamespace(username="smart_city_bot", user_id=777),
        send_message=AsyncMock(),
    )


def test_welcome_text_contains_product_description_and_docs() -> None:
    text = start.build_welcome_text("Алексей")
    assert text.startswith("Привет, Алексей!")
    assert "районных чатов" in text
    assert "городских источников" in text
    assert start.DOCS_URL in text


def test_welcome_keyboard_has_fixed_button_copy() -> None:
    markup = start.build_welcome_keyboard(_bot())
    buttons = markup.payload.buttons

    assert len(buttons) == 1
    assert [button.text for button in buttons[0]] == ["Добавить чат", "Смотреть события"]
    assert buttons[0][0].payload == start.CHAT_LINK_START_PAYLOAD
    assert buttons[0][1].web_app == "smart_city_bot"
    assert buttons[0][1].contact_id == 777


def test_bot_started_sends_welcome(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _bot()
    monkeypatch.setattr(
        start,
        "authorize_from_event",
        lambda event: SimpleNamespace(name="Алексей", username="alexey"),
    )
    start.register_auth_commands(dp, bot)

    event = SimpleNamespace(chat_id=123)
    asyncio.run(dp.handlers["bot_started"](event))

    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 123
    assert kwargs["text"] == start.build_welcome_text("Алексей")
    assert len(kwargs["attachments"]) == 1


def test_start_sends_same_welcome(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _bot()
    monkeypatch.setattr(
        start,
        "authorize_from_event",
        lambda event: SimpleNamespace(name=None, username="alexey"),
    )
    start.register_auth_commands(dp, bot)

    message = SimpleNamespace(answer=AsyncMock())
    event = SimpleNamespace(message=message)
    asyncio.run(dp.handlers["message_created"](event))

    message.answer.assert_awaited_once()
    kwargs = message.answer.await_args.kwargs
    assert kwargs["text"] == start.build_welcome_text("alexey")
    assert len(kwargs["attachments"]) == 1


def test_add_chat_is_mock_until_kan_7() -> None:
    dp = FakeDispatcher()
    bot = _bot()
    start.register_auth_commands(dp, bot)

    event = SimpleNamespace(answer=AsyncMock())
    asyncio.run(dp.handlers["message_callback"](event))

    event.answer.assert_awaited_once_with(notification=start.CHAT_LINK_MOCK_NOTIFICATION)
