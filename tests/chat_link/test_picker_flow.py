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
    event.ack.assert_awaited_once()
    assert "Сельскохозяйственная улица" in event.edit.await_args.kwargs["text"]
    assert "Выберите дом" in event.edit.await_args.kwargs["text"]
    assert context.data["street"] == "Сельскохозяйственная улица"
