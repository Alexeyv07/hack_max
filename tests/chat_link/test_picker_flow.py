from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import chat_link.commands.flow as flow


class FakeDispatcher:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def _decorator(self, name: str):
        def register(func):
            self.handlers[name] = func
            return func

        return register

    def message_callback(self, *args, **kwargs):
        return self._decorator("message_callback")

    def message_created(self, *args, **kwargs):
        return self._decorator("message_created")

    def bot_added(self, *args, **kwargs):
        return self._decorator("bot_added")

    def bot_removed(self, *args, **kwargs):
        return self._decorator("bot_removed")

    def user_added(self, *args, **kwargs):
        return self._decorator("user_added")


class FakeContext:
    def __init__(self, data=None) -> None:
        self.data = dict(data or {})
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)
        return dict(self.data)

    async def set_state(self, state):
        self.state = state

    async def set_data(self, data):
        self.data = dict(data)
        return dict(self.data)


class PostalCatalog:
    def postal_streets(self, postal_code):
        assert postal_code == "129226"
        return ["Сельскохозяйственная улица", "улица Вильгельма Пика"]

    def postal_houses(self, postal_code, street):
        assert postal_code == "129226"
        assert street == "Сельскохозяйственная улица"
        return [SimpleNamespace(id=11, house="15 к1", district="Ростокино", city="Москва")]


def test_postal_goes_straight_to_streets_without_city_or_district(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace(edit_message=AsyncMock())
    monkeypatch.setattr(flow, "get_address_catalog", lambda: PostalCatalog())
    flow.register_chat_link_commands(dp, bot)

    context = FakeContext({"flow_mid": "onboarding-mid"})
    event = SimpleNamespace(
        message=SimpleNamespace(body=SimpleNamespace(text="129226")),
    )

    asyncio.run(dp.handlers["message_created"](event, context))

    bot.edit_message.assert_awaited_once()
    kwargs = bot.edit_message.await_args.kwargs
    assert "Индекс 129226 → выберите улицу" in kwargs["text"]
    assert "город" not in kwargs["text"].casefold()
    assert "район" not in kwargs["text"].casefold()
    assert context.data == {"flow_mid": "onboarding-mid", "postal_code": "129226"}


class MissingPostalCatalog:
    def postal_streets(self, postal_code):
        return []


def test_invalid_postal_format_shows_error_and_keeps_back_button(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace(edit_message=AsyncMock())
    flow.register_chat_link_commands(dp, bot)

    context = FakeContext({"flow_mid": "onboarding-mid"})
    event = SimpleNamespace(
        message=SimpleNamespace(body=SimpleNamespace(text="12922")),
    )

    asyncio.run(dp.handlers["message_created"](event, context))

    bot.edit_message.assert_awaited_once()
    kwargs = bot.edit_message.await_args.kwargs
    assert kwargs["text"].startswith("❗ Ошибка ❗")
    assert "ровно из 6 цифр" in kwargs["text"]
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "← Назад"
    assert buttons[0][0].payload == "cl:back:root"


def test_unknown_postal_keeps_back_button(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace(edit_message=AsyncMock())
    monkeypatch.setattr(flow, "get_address_catalog", lambda: MissingPostalCatalog())
    flow.register_chat_link_commands(dp, bot)

    context = FakeContext({"flow_mid": "onboarding-mid"})
    event = SimpleNamespace(
        message=SimpleNamespace(body=SimpleNamespace(text="000000")),
    )

    asyncio.run(dp.handlers["message_created"](event, context))

    bot.edit_message.assert_awaited_once()
    kwargs = bot.edit_message.await_args.kwargs
    assert kwargs["text"].startswith("❗ Ошибка ❗")
    assert "Такого индекса нет" in kwargs["text"]
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "← Назад"
    assert buttons[0][0].payload == "cl:back:root"


def test_postal_street_callback_goes_to_houses(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace()
    monkeypatch.setattr(flow, "get_address_catalog", lambda: PostalCatalog())
    flow.register_chat_link_commands(dp, bot)

    context = FakeContext({"flow_mid": "mid", "postal_code": "129226"})
    event = SimpleNamespace(
        callback=SimpleNamespace(
            payload="cl:postal_street:pick:0",
            user=SimpleNamespace(user_id=123),
        ),
        ack=AsyncMock(),
        edit=AsyncMock(),
        message=SimpleNamespace(body=SimpleNamespace(mid="mid")),
    )

    asyncio.run(dp.handlers["message_callback"](event, context))

    event.edit.assert_awaited_once()
    event.ack.assert_not_awaited()
    assert "Сельскохозяйственная улица" in event.edit.await_args.kwargs["text"]
    assert "Выберите дом" in event.edit.await_args.kwargs["text"]
    assert context.data["street"] == "Сельскохозяйственная улица"


class RoleCatalog:
    def get(self, address_id):
        if address_id != 42:
            return None
        return SimpleNamespace(id=42, address_text="Москва, Ростокино, д. 1")


def _role_event(payload: str):
    return SimpleNamespace(
        callback=SimpleNamespace(
            payload=payload,
            user=SimpleNamespace(user_id=123),
        ),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )


def test_admin_instructions_are_shown_only_after_admin_button(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace(me=SimpleNamespace(username="test_bot", user_id=999))
    monkeypatch.setattr(flow, "get_address_catalog", lambda: RoleCatalog())
    flow.register_chat_link_commands(dp, bot)

    context = FakeContext({"address_id": 42, "link_token": "token"})
    event = _role_event("cl:admin:help")

    asyncio.run(dp.handlers["message_callback"](event, context))

    event.ack.assert_not_awaited()
    event.edit.assert_awaited_once()
    kwargs = event.edit.await_args.kwargs
    assert "Если вы администратор домового чата" in kwargs["text"]
    assert "Читать все сообщения" in kwargs["text"]
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "← Я не администратор"


def test_return_from_admin_help_shows_resident_text(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace(me=SimpleNamespace(username="test_bot", user_id=999))
    monkeypatch.setattr(flow, "get_address_catalog", lambda: RoleCatalog())
    monkeypatch.setattr(
        flow,
        "create_start_link",
        lambda username, payload: f"https://max.ru/{username}?start={payload}",
    )
    flow.register_chat_link_commands(dp, bot)

    context = FakeContext({"address_id": 42, "link_token": "token"})
    event = _role_event("cl:admin:user")

    asyncio.run(dp.handlers["message_callback"](event, context))

    event.ack.assert_not_awaited()
    event.edit.assert_awaited_once()
    kwargs = event.edit.await_args.kwargs
    assert "Если вы обычный житель" in kwargs["text"]
    assert "Если вы администратор домового чата" not in kwargs["text"]
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "Скопировать ссылку для админа"
    assert buttons[1][0].text == "Я администратор чата"


def test_method_screen_uses_regular_message_edit(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace(
        me=SimpleNamespace(username="test_bot", user_id=999),
        edit_message=AsyncMock(),
    )
    flow.register_chat_link_commands(dp, bot)

    context = FakeContext({"flow_mid": "mid"})
    event = SimpleNamespace(
        callback=SimpleNamespace(
            payload="chat_link:start",
            user=SimpleNamespace(user_id=123),
        ),
        ack=AsyncMock(),
        edit=AsyncMock(),
        message=SimpleNamespace(body=SimpleNamespace(mid="mid")),
    )

    asyncio.run(dp.handlers["message_callback"](event, context))

    event.ack.assert_awaited_once()
    event.edit.assert_not_awaited()
    bot.edit_message.assert_awaited_once()
    args = bot.edit_message.await_args.args
    kwargs = bot.edit_message.await_args.kwargs
    assert args == ("mid",)
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[-1][0].text == "← Назад"


def test_method_screen_has_back_to_welcome_button() -> None:
    from chat_link.commands.keyboards import method_keyboard

    bot = SimpleNamespace(me=SimpleNamespace(username="test_bot", user_id=999))
    markup = method_keyboard(bot)
    buttons = markup.payload.buttons

    assert len(buttons) == 5
    assert buttons[-1][0].text == "← Назад"
    assert buttons[-1][0].payload == "cl:back:welcome"


def test_back_from_method_screen_returns_to_welcome(monkeypatch) -> None:
    from contextlib import contextmanager

    dp = FakeDispatcher()
    bot = SimpleNamespace(
        me=SimpleNamespace(username="test_bot", user_id=999),
        edit_message=AsyncMock(),
    )

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        flow,
        "get_user_by_max_id",
        lambda _session, max_user_id: SimpleNamespace(
            max_user_id=max_user_id,
            name="Алексей",
            username="alexey",
        ),
    )
    monkeypatch.setattr(flow, "has_connected_chat", lambda _session, _max_user_id: False)
    flow.register_chat_link_commands(dp, bot)

    context = FakeContext(
        {
            "flow_mid": "mid",
            "city": "Москва",
            "district": "Ростокино",
        }
    )
    event = SimpleNamespace(
        callback=SimpleNamespace(
            payload="cl:back:welcome",
            user=SimpleNamespace(user_id=123),
        ),
        ack=AsyncMock(),
        edit=AsyncMock(),
        message=SimpleNamespace(body=SimpleNamespace(mid="mid")),
    )

    asyncio.run(dp.handlers["message_callback"](event, context))

    event.ack.assert_awaited_once()
    event.edit.assert_not_awaited()
    bot.edit_message.assert_awaited_once()
    assert bot.edit_message.await_args.args == ("mid",)
    kwargs = bot.edit_message.await_args.kwargs
    assert kwargs["text"].startswith("Привет, Алексей!")
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "Добавить чат"
    assert context.data == {"flow_mid": "mid"}
    assert context.state is None
