from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import chat_link.commands.flow as flow
from chat_link.commands.keyboards import add_more_addresses_keyboard
from chat_link.models import ConnectOutcome


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

    def user_removed(self, *args, **kwargs):
        return self._decorator("user_removed")

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


def test_admin_setup_explains_how_to_add_address_to_existing_chat(monkeypatch) -> None:
    monkeypatch.setattr(
        flow,
        "get_address_catalog",
        lambda: SimpleNamespace(get=lambda address_id: SimpleNamespace(address_text="Дом 2")),
    )
    event = SimpleNamespace(edit=AsyncMock())

    asyncio.run(flow._show_admin_setup(event, FakeContext({"address_id": 2}), bot=None))

    text = event.edit.await_args.kwargs["text"]
    assert "повторно добавлять его не нужно" in text
    assert "/address" in text
    assert "Добавить адрес чата (админ)" in text


def test_add_more_addresses_button_reuses_group_binding_flow() -> None:
    button = add_more_addresses_keyboard().payload.buttons[0][0]
    assert button.text == "Добавить ещё адрес"
    assert button.payload == "chat_link:start"


def test_admin_can_add_next_address_without_readding_bot(monkeypatch) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    connect = AsyncMock(return_value=ConnectOutcome(True, -100500, True, "Адрес добавлен к чату."))
    announce = AsyncMock()
    home = AsyncMock()
    monkeypatch.setattr(flow, "_complete_with_home", home)
    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        flow,
        "get_address_catalog",
        lambda: SimpleNamespace(get=lambda address_id: SimpleNamespace(address_text="Дом 2")),
    )
    monkeypatch.setattr(flow, "connect_added_group_to_address", connect)
    monkeypatch.setattr(flow, "announce_connected_group", announce)

    bot = SimpleNamespace(
        me=SimpleNamespace(username="test_bot", user_id=999),
        edit_message=AsyncMock(),
    )
    context = FakeContext({"target_chat_id": -100500, "flow_mid": "mid"})
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="", user=SimpleNamespace(user_id=101)),
        message=SimpleNamespace(body=SimpleNamespace(mid="mid")),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )
    asyncio.run(flow._finish_address(event, context, bot, address_id=2))

    connect.assert_awaited_once()
    home.assert_awaited_once()
    assert home.await_args.args[:3] == (event, bot, 101)
    assert "Чат привязан" in (home.await_args.kwargs.get("notice") or "")
    assert connect.await_args.kwargs["chat_id"] == -100500
    assert context.data == {}
    announce.assert_awaited_once()
    event.edit.assert_not_awaited()


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
    assert "Как выбрать адрес" in kwargs["text"]


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
    assert "Как выбрать адрес" in kwargs["text"]


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
    assert "Если бот уже есть в вашем чате" in kwargs["text"]
    assert "Читать все сообщения" in kwargs["text"]
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "← Я не администратор"
    assert "Подключение чата" in kwargs["text"]
    assert "<a href=" in kwargs["text"]


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
    assert "Скопируйте пригласительное сообщение" in kwargs["text"]
    assert "Если бот уже есть в вашем чате" not in kwargs["text"]
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "Скопировать ссылку"
    assert buttons[1][0].text == "Я администратор"


def test_method_screen_uses_regular_message_edit(monkeypatch) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
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
    assert [button[0].text for button in buttons[:4]] == [
        "Выбрать адрес",
        "Указать почтовый индекс",
        "Указать на карте",
        "Ввести текстом",
    ]
    assert [buttons[0][0].payload, buttons[1][0].payload] == [
        "cl:method:native",
        "cl:method:postal",
    ]
    assert buttons[2][0].payload == "chat_link_map"
    assert buttons[3][0].payload == "chat_link_text"
    assert buttons[-1][0].text == "← Назад"
    assert buttons[-1][0].payload == "cl:back:welcome"
    manage = method_keyboard(bot, from_manage=True)
    assert manage.payload.buttons[-1][0].payload == "cl:back:manage"


def test_manage_start_returns_to_address_list(monkeypatch) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        flow,
        "build_manage_list_view",
        lambda _uid, page=0, notice=None: (
            "Ваши адреса",
            SimpleNamespace(payload=SimpleNamespace(buttons=[])),
        ),
    )
    dp = FakeDispatcher()
    bot = SimpleNamespace(
        me=SimpleNamespace(username="test_bot", user_id=999),
        edit_message=AsyncMock(),
    )
    flow.register_chat_link_commands(dp, bot)
    context = FakeContext({"from_manage": True, "flow_mid": "mid"})
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="cl:back:manage", user=SimpleNamespace(user_id=123)),
        message=SimpleNamespace(body=SimpleNamespace(mid="mid")),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )
    asyncio.run(dp.handlers["message_callback"](event, context))
    bot.edit_message.assert_awaited_once()
    assert bot.edit_message.await_args.kwargs["text"] == "Ваши адреса"


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
    monkeypatch.setattr(flow, "user_can_see_events", lambda _max_user_id: False)
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
    assert kwargs["text"].startswith("Давайте найдём ваш дом")
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "Выбрать адрес"
    assert context.data == {"flow_mid": "mid"}
    assert context.state is None


def test_first_welcome_is_edited_into_address_picker(monkeypatch) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    dp = FakeDispatcher()
    bot = SimpleNamespace(
        me=SimpleNamespace(username="test_bot", user_id=999),
        send_message=AsyncMock(),
        edit_message=AsyncMock(),
    )
    flow.register_chat_link_commands(dp, bot)
    context = FakeContext({"first_welcome_mid": "first-mid", "flow_mid": "first-mid"})
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="chat_link:start", user=SimpleNamespace(user_id=123)),
        message=SimpleNamespace(body=SimpleNamespace(mid="first-mid")),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )
    asyncio.run(dp.handlers["message_callback"](event, context))
    bot.send_message.assert_not_awaited()
    bot.edit_message.assert_awaited_once()
    assert bot.edit_message.await_args.args == ("first-mid",)
    assert context.data.get("first_welcome_mid") is None
    assert context.data["flow_mid"] == "first-mid"


def test_address_button_allows_outsider_to_choose_without_granting_feed(monkeypatch) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    dp = FakeDispatcher()
    bot = SimpleNamespace(edit_message=AsyncMock())
    flow.register_chat_link_commands(dp, bot)
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="chat_link:start", user=SimpleNamespace(user_id=42)),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )

    asyncio.run(dp.handlers["message_callback"](event, FakeContext()))

    event.edit.assert_awaited_once()
    assert "Давайте найдём ваш дом" in event.edit.await_args.kwargs["text"]
    bot.edit_message.assert_not_awaited()


def test_group_admin_removes_address_and_updates_announcement(db_session, monkeypatch) -> None:
    from decimal import Decimal

    from address.db import AddressRow
    from user_chat.handlers import add_chat_address, create_chat, list_chat_addresses
    from user_chat.models import ChatCreate

    first = AddressRow(
        address_text="Москва, Админская улица, д. 1",
        latitude=Decimal("55.7"),
        longitude=Decimal("37.6"),
    )
    second = AddressRow(
        address_text="Москва, Админская улица, д. 2",
        latitude=Decimal("55.7"),
        longitude=Decimal("37.6"),
    )
    db_session.add_all([first, second])
    db_session.flush()
    create_chat(db_session, ChatCreate(chat_id=-8123, address_id=first.id))
    add_chat_address(db_session, -8123, second.id)

    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(flow, "session_scope", same_session)
    monkeypatch.setattr(flow, "bot_can_read_group", AsyncMock(return_value=True))
    announce = AsyncMock()
    monkeypatch.setattr(flow, "announce_connected_group", announce)
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(is_admin=True, is_owner=False)),
        send_message=AsyncMock(),
        edit_message=AsyncMock(),
    )
    dp = FakeDispatcher()
    flow.register_chat_link_commands(dp, bot)
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="cl:group:remove:-8123", user=SimpleNamespace(user_id=41)),
        message=SimpleNamespace(body=SimpleNamespace(mid="delete-choice")),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )
    asyncio.run(dp.handlers["message_callback"](event, FakeContext()))
    bot.send_message.assert_not_awaited()
    buttons = bot.edit_message.await_args.kwargs["attachments"][0].payload.buttons
    assert "Какой адрес убрать" in bot.edit_message.await_args.kwargs["text"]
    assert len(buttons) == 2
    assert buttons[1][0].payload == f"cl:group:pick:-8123:{second.id}"
    event.callback.payload = buttons[1][0].payload
    bot.edit_message.reset_mock()
    asyncio.run(dp.handlers["message_callback"](event, FakeContext()))
    assert [address.id for address in list_chat_addresses(db_session, -8123)] == [first.id]
    announce.assert_awaited_once_with(bot, -8123)
    bot.edit_message.assert_awaited_once()
    assert bot.edit_message.await_args.args == ("delete-choice",)
    assert "больше не привязан" in bot.edit_message.await_args.kwargs["text"]


def test_non_admin_cannot_remove_group_address(monkeypatch) -> None:
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(is_admin=False, is_owner=False)),
        send_message=AsyncMock(),
    )
    dp = FakeDispatcher()
    flow.register_chat_link_commands(dp, bot)
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="cl:group:remove:-8123", user=SimpleNamespace(user_id=42)),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )
    asyncio.run(dp.handlers["message_callback"](event, FakeContext()))
    assert "администратору" in event.ack.await_args.kwargs["notification"]
    bot.send_message.assert_not_awaited()
