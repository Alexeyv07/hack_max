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
    event = SimpleNamespace(
        edit=AsyncMock(), callback=SimpleNamespace(user=SimpleNamespace(user_id=123))
    )

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(flow, "eligible_admin_groups", AsyncMock(return_value=[]))

    asyncio.run(flow._show_admin_setup(event, FakeContext({"address_id": 2}), bot=None))

    text = event.edit.await_args.kwargs["text"]
    assert "Добавьте бота" in text
    assert "Проверить еще раз" in text


def test_native_resident_retry_shows_success_only_after_max_confirms(monkeypatch) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    lookup = AsyncMock(side_effect=[None, object()])
    resolve = AsyncMock(
        side_effect=[
            SimpleNamespace(mode="not_member", token=None),
            SimpleNamespace(mode="personal_address", token=None),
        ]
    )
    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(flow, "resolve_residence", resolve)
    monkeypatch.setattr(
        flow,
        "get_address_catalog",
        lambda: SimpleNamespace(get=lambda address_id: SimpleNamespace(address_text="Дом 1")),
    )
    bot = SimpleNamespace(get_chat_member=lookup)
    dp = FakeDispatcher()
    flow.register_chat_link_commands(dp, bot)
    context = FakeContext()
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="", user=SimpleNamespace(user_id=101)),
        edit=AsyncMock(),
        ack=AsyncMock(),
        message=SimpleNamespace(body=SimpleNamespace(mid="mid")),
    )

    asyncio.run(flow._finish_residence(event, context, bot, 12))
    buttons = event.edit.await_args.kwargs["attachments"][0].payload.buttons
    assert [row[0].text for row in buttons] == ["Проверить еще раз", "Назад"]
    assert buttons[0][0].payload == "cl:residence:retry:12"

    event.callback.payload = buttons[0][0].payload
    asyncio.run(dp.handlers["message_callback"](event, context))
    buttons = event.edit.await_args.kwargs["attachments"][0].payload.buttons
    assert "Чат успешно добавлен" in event.edit.await_args.kwargs["text"]
    assert buttons[0][0].text == "На главную"
    assert context.data == {}
    assert resolve.await_count == 2


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
    assert announce.await_args.kwargs["new_message"] is True
    event.edit.assert_not_awaited()


def test_native_admin_confirmation_sends_fresh_welcome(monkeypatch) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        flow,
        "get_address_catalog",
        lambda: SimpleNamespace(get=lambda address_id: SimpleNamespace(address_text="Дом 2")),
    )
    monkeypatch.setattr(
        flow,
        "eligible_admin_group",
        AsyncMock(return_value=SimpleNamespace(chat_id=-321, title="Наш двор")),
    )
    monkeypatch.setattr(
        flow,
        "connect_added_group_to_address",
        AsyncMock(return_value=ConnectOutcome(True, -321, True)),
    )
    announce = AsyncMock()
    monkeypatch.setattr(flow, "announce_connected_group", announce)
    context = FakeContext()
    event = SimpleNamespace(
        callback=SimpleNamespace(user=SimpleNamespace(user_id=101)),
        edit=AsyncMock(),
        ack=AsyncMock(),
    )

    asyncio.run(flow._confirm_admin_group(event, context, object(), address_id=2, chat_id=-321))

    assert announce.await_args.kwargs["new_message"] is True
    assert "успешно привязан" in event.edit.await_args.kwargs["text"]

    announce.side_effect = RuntimeError("MAX unavailable")
    event.edit.reset_mock()
    asyncio.run(flow._confirm_admin_group(event, context, object(), address_id=2, chat_id=-321))
    assert "Приветствие не удалось отправить" in event.edit.await_args.kwargs["text"]


class PostalCatalog:
    def postal_streets(self, postal_code):
        assert postal_code == "129226"
        return ["Сельскохозяйственная улица", "улица Вильгельма Пика"]

    def postal_houses(self, postal_code, street):
        assert postal_code == "129226"
        assert street == "Сельскохозяйственная улица"
        return [SimpleNamespace(id=11, house="15 к1", district="Ростокино", city="Москва")]


def _postal_event(text: str):
    # MAX сообщает и чат, и автора личного сообщения.
    return SimpleNamespace(
        chat_id=123,
        message=SimpleNamespace(
            sender=SimpleNamespace(user_id=42),
            body=SimpleNamespace(mid="user-input", text=text),
        ),
    )


def _postal_bot():
    return SimpleNamespace(
        send_message=AsyncMock(
            return_value=SimpleNamespace(
                message=SimpleNamespace(body=SimpleNamespace(mid="new-mid"))
            )
        ),
        edit_message=AsyncMock(),
        delete_message=AsyncMock(),
    )


def test_postal_goes_straight_to_streets_without_city_or_district(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _postal_bot()
    monkeypatch.setattr(flow, "get_address_catalog", lambda: PostalCatalog())
    flow.register_chat_link_commands(dp, bot)
    context = FakeContext({"flow_mid": "onboarding-mid"})

    asyncio.run(dp.handlers["message_created"](_postal_event("129226"), context))

    bot.edit_message.assert_not_awaited()
    sent = bot.send_message.await_args.kwargs
    assert sent["chat_id"] == 123
    assert "Индекс 129226 → выберите улицу" in sent["text"]
    assert "город" not in sent["text"].casefold()
    assert "район" not in sent["text"].casefold()
    assert context.data == {"flow_mid": "new-mid", "postal_code": "129226"}
    bot.delete_message.assert_awaited_once_with("onboarding-mid")
    assert bot.delete_message.await_args.args != ("user-input",)


class MissingPostalCatalog:
    def postal_streets(self, postal_code):
        return []


def test_invalid_postal_format_shows_error_and_keeps_back_button(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _postal_bot()
    flow.register_chat_link_commands(dp, bot)
    context = FakeContext({"flow_mid": "onboarding-mid"})

    asyncio.run(dp.handlers["message_created"](_postal_event("12922"), context))

    bot.edit_message.assert_not_awaited()
    sent = bot.send_message.await_args.kwargs
    assert sent["text"].startswith("❗ Ошибка ❗")
    assert "ровно из 6 цифр" in sent["text"]
    buttons = sent["attachments"][0].payload.buttons
    assert buttons[0][0].text == "← Назад"
    assert buttons[0][0].payload == "cl:back:root"
    assert "Как выбрать адрес" in sent["text"]
    assert context.data["flow_mid"] == "new-mid"
    bot.delete_message.assert_awaited_once_with("onboarding-mid")


def test_unknown_postal_keeps_back_button(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _postal_bot()
    monkeypatch.setattr(flow, "get_address_catalog", lambda: MissingPostalCatalog())
    flow.register_chat_link_commands(dp, bot)
    context = FakeContext({"flow_mid": "onboarding-mid"})

    asyncio.run(dp.handlers["message_created"](_postal_event("000000"), context))

    bot.edit_message.assert_not_awaited()
    sent = bot.send_message.await_args.kwargs
    assert sent["text"].startswith("❗ Ошибка ❗")
    assert "Такого индекса нет" in sent["text"]
    buttons = sent["attachments"][0].payload.buttons
    assert buttons[0][0].text == "← Назад"
    assert buttons[0][0].payload == "cl:back:root"
    assert "Как выбрать адрес" in sent["text"]
    bot.delete_message.assert_awaited_once_with("onboarding-mid")


def test_second_invalid_postal_replaces_previous_error_not_user_message() -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=[
                SimpleNamespace(message=SimpleNamespace(body=SimpleNamespace(mid="first-error"))),
                SimpleNamespace(message=SimpleNamespace(body=SimpleNamespace(mid="second-error"))),
            ]
        ),
        edit_message=AsyncMock(),
        delete_message=AsyncMock(),
    )
    flow.register_chat_link_commands(dp, bot)
    context = FakeContext({"flow_mid": "original-screen"})
    handler = dp.handlers["message_created"]

    async def scenario():
        await handler(_postal_event("12"), context)
        await handler(_postal_event("123"), context)

    asyncio.run(scenario())
    assert bot.send_message.await_count == 2
    assert [call.args[0] for call in bot.delete_message.await_args_list] == [
        "original-screen",
        "first-error",
    ]
    assert context.data["flow_mid"] == "second-error"
    bot.edit_message.assert_not_awaited()


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

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(flow, "eligible_admin_groups", AsyncMock(return_value=[]))
    context = FakeContext({"address_id": 42, "link_token": "token"})
    event = _role_event("cl:admin:help")

    asyncio.run(dp.handlers["message_callback"](event, context))

    event.ack.assert_not_awaited()
    event.edit.assert_awaited_once()
    kwargs = event.edit.await_args.kwargs
    assert "Добавьте бота" in kwargs["text"]
    assert "Читать все сообщения" in kwargs["text"]
    buttons = kwargs["attachments"][0].payload.buttons
    assert [row[0].text for row in buttons] == ["Проверить еще раз", "Назад"]


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
    assert "Для этого дома пока нет подключённого чата" in kwargs["text"]
    assert "Если бот уже есть в вашем чате" not in kwargs["text"]
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "Скопировать пригласительное сообщение"
    assert buttons[1][0].text == "Я админ чата"


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


def test_old_group_buttons_do_not_change_addresses(db_session, monkeypatch) -> None:
    """Старые сообщения в группе больше не дают управлять адресами."""
    from decimal import Decimal

    from address.db import AddressRow
    from user_chat.handlers import add_chat_address, create_chat, list_chat_addresses
    from user_chat.models import ChatCreate

    first = AddressRow(
        address_text="Москва, ул. Первая, д. 1", latitude=Decimal("55.7"), longitude=Decimal("37.6")
    )
    second = AddressRow(
        address_text="Москва, ул. Первая, д. 2", latitude=Decimal("55.7"), longitude=Decimal("37.6")
    )
    db_session.add_all([first, second])
    db_session.flush()
    create_chat(db_session, ChatCreate(chat_id=-8123, address_id=first.id))
    add_chat_address(db_session, -8123, second.id)

    bot = SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock())
    dp = FakeDispatcher()
    flow.register_chat_link_commands(dp, bot)
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="cl:group:remove:-8123", user=SimpleNamespace(user_id=41)),
        message=SimpleNamespace(
            recipient=SimpleNamespace(chat_type="chat", chat_id=-8123),
            body=SimpleNamespace(mid="old-button"),
        ),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )
    asyncio.run(dp.handlers["message_callback"](event, FakeContext()))
    assert [address.id for address in list_chat_addresses(db_session, -8123)] == [
        first.id,
        second.id,
    ]
    event.ack.assert_awaited_once()
    bot.send_message.assert_not_awaited()
    bot.edit_message.assert_not_awaited()


def test_group_admin_button_is_private_only() -> None:
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(is_admin=False, is_owner=False)),
        send_message=AsyncMock(),
    )
    dp = FakeDispatcher()
    flow.register_chat_link_commands(dp, bot)
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="cl:group:remove:-8123", user=SimpleNamespace(user_id=42)),
        message=SimpleNamespace(recipient=SimpleNamespace(chat_type="chat", chat_id=-8123)),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )
    asyncio.run(dp.handlers["message_callback"](event, FakeContext()))
    assert "личном чате" in event.ack.await_args.kwargs["notification"]
    bot.send_message.assert_not_awaited()


def test_add_address_from_chat_menu_preserves_target_and_back(monkeypatch) -> None:
    from chat_link.handlers.registry import AdminGroup

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        flow,
        "eligible_admin_group",
        AsyncMock(return_value=AdminGroup(chat_id=-8123, title="Наш двор")),
    )
    monkeypatch.setattr(
        flow, "get_chat", lambda _session, _chat_id: SimpleNamespace(chat_type="chat")
    )
    monkeypatch.setattr(flow, "connected_admin_groups", AsyncMock(return_value=[]))
    bot = SimpleNamespace(
        me=SimpleNamespace(username="test_bot", user_id=999), edit_message=AsyncMock()
    )
    event = SimpleNamespace(
        callback=SimpleNamespace(
            payload="chat_link:start:chat:-8123", user=SimpleNamespace(user_id=42)
        ),
        message=SimpleNamespace(body=SimpleNamespace(mid="chat-selection")),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )
    context = FakeContext()
    dp = FakeDispatcher()
    flow.register_chat_link_commands(dp, bot)

    asyncio.run(dp.handlers["message_callback"](event, context))
    assert context.data["target_chat_id"] == -8123
    assert context.data["from_chats"] is True
    buttons = bot.edit_message.await_args.kwargs["attachments"][0].payload.buttons
    assert buttons[-1][0].payload == "cl:back:chats"

    event.callback.payload = "cl:back:chats"
    asyncio.run(dp.handlers["message_callback"](event, context))
    assert "Управление чатами" in bot.edit_message.await_args.kwargs["text"]


def test_postal_street_back_returns_to_postal_input(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _postal_bot()
    monkeypatch.setattr(flow, "get_address_catalog", lambda: PostalCatalog())
    flow.register_chat_link_commands(dp, bot)
    context = FakeContext({"flow_mid": "postal-mid"})

    asyncio.run(dp.handlers["message_created"](_postal_event("129226"), context))
    street_buttons = bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
    assert any(button.payload == "cl:back:postal" for row in street_buttons for button in row)

    event = SimpleNamespace(
        callback=SimpleNamespace(payload="cl:back:postal", user=SimpleNamespace(user_id=123)),
        edit=AsyncMock(),
        message=SimpleNamespace(body=SimpleNamespace(mid="new-mid")),
    )
    asyncio.run(dp.handlers["message_callback"](event, context))
    assert "Введите шестизначный" in event.edit.await_args.kwargs["text"]
    assert context.data["postal_code"] == "129226"
    assert (
        event.edit.await_args.kwargs["attachments"][0].payload.buttons[0][0].payload
        == "cl:back:root"
    )
