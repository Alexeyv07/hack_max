"""KAN-8/KAN-7: приветственный экран Max-бота."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import auth.commands.start as start


class FakeContext:
    def __init__(self, data=None) -> None:
        self.data = dict(data or {})

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.data.clear()

    async def update_data(self, **kwargs):
        self.data.update(kwargs)
        return dict(self.data)


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
    sent = SimpleNamespace(message=SimpleNamespace(body=SimpleNamespace(mid="welcome-mid")))
    return SimpleNamespace(
        me=SimpleNamespace(username="smart_city_bot", user_id=777),
        send_message=AsyncMock(return_value=sent),
        edit_message=AsyncMock(),
    )


def _user(name="Алексей", username="alexey", *, is_new=False):
    return SimpleNamespace(name=name, username=username, max_user_id=42, is_new=is_new)


def test_first_welcome_matches_product_copy() -> None:
    text = start.build_welcome_text("Алексей")
    assert text.startswith("Здравствуйте, Алексей!")
    assert "Это сервис «КасаетсяМеня»" in text
    assert "что произойдёт, когда и касается ли это вашего дома и корпуса" in text
    assert "Укажите свой адрес" in text


def test_admin_deep_link_explains_automatic_group_connection() -> None:
    text = start.build_welcome_text("Админ", admin_token="secret")
    assert "назначьте его администратором" in text
    assert "автоматически" in text
    assert "/connect" not in text


def test_welcome_keyboard_hides_events_without_membership() -> None:
    markup = start.build_welcome_keyboard(_bot(), show_events=False)
    buttons = markup.payload.buttons
    assert [button.text for button in buttons[0]] == ["Указать свой адрес"]
    assert start.build_welcome_keyboard(_bot(), show_events=False, can_choose_address=False) is None


def test_welcome_keyboard_shows_events_after_membership() -> None:
    markup = start.build_welcome_keyboard(_bot(), show_events=True)
    buttons = markup.payload.buttons
    assert [button.text for button in buttons[0]] == ["Указать свой адрес", "Смотреть события"]
    assert buttons[0][0].payload == start.CHAT_LINK_START_PAYLOAD
    assert buttons[0][1].web_app == "smart_city_bot"
    assert buttons[0][1].contact_id == 777


def test_bot_started_sends_welcome(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _bot()
    monkeypatch.setattr(start, "authorize_from_event", lambda event: _user(is_new=True))
    monkeypatch.setattr(start, "_show_events", lambda max_user_id: False)
    monkeypatch.setattr(start, "_can_choose_address", lambda max_user_id: True)
    start.register_auth_commands(dp, bot)

    context = FakeContext()
    event = SimpleNamespace(chat_id=123, payload=None)
    asyncio.run(dp.handlers["bot_started"](event, context))

    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 123
    assert kwargs["text"] == start.build_welcome_text("Алексей")
    assert context.data["flow_mid"] == "welcome-mid"


def test_repeat_start_opens_home_after_address_selected(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _bot()
    monkeypatch.setattr(start, "authorize_from_event", lambda event: _user(name=None, is_new=False))
    monkeypatch.setattr(start, "_show_events", lambda max_user_id: True)
    monkeypatch.setattr(start, "_can_choose_address", lambda max_user_id: True)

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(start, "session_scope", fake_session_scope)

    async def fake_home(bot, session, max_user_id, *, recipient_chat_id=None):
        assert max_user_id == 42
        assert recipient_chat_id == 123
        return await bot.send_message(chat_id=123, text="<b>Главная</b>", attachments=[])

    monkeypatch.setattr(start, "send_home", fake_home)
    start.register_auth_commands(dp, bot)

    context = FakeContext({"flow_mid": "old-mid", "postal_code": "123456"})
    event = SimpleNamespace(
        chat_id=123,
        message=SimpleNamespace(recipient=SimpleNamespace(chat_id=123)),
    )
    asyncio.run(dp.handlers["message_created"](event, context))

    bot.edit_message.assert_not_awaited()
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 123
    assert "Главная" in bot.send_message.await_args.kwargs["text"]
    assert context.data == {"flow_mid": "welcome-mid"}


def test_group_bind_deep_link_keeps_target_chat_in_context(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _bot()
    monkeypatch.setattr(start, "authorize_from_event", lambda event: _user())
    monkeypatch.setattr(start, "_show_events", lambda max_user_id: False)
    monkeypatch.setattr(start, "_can_choose_address", lambda max_user_id: True)

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(start, "session_scope", fake_session_scope)
    start.register_auth_commands(dp, bot)

    context = FakeContext()
    event = SimpleNamespace(chat_id=123, payload="chat_bind_-100500")
    asyncio.run(dp.handlers["bot_started"](event, context))

    assert context.data["target_chat_id"] == -100500
    assert context.data["flow_mid"] == "welcome-mid"
    kwargs = bot.send_message.await_args.kwargs
    assert "уже добавленный групповой чат" in kwargs["text"]
    buttons = kwargs["attachments"][0].payload.buttons
    assert buttons[0][0].text == "Добавить адрес чата"


def test_plain_start_delivered_as_two_update_types_sends_one_welcome(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _bot()
    monkeypatch.setattr(start, "authorize_from_event", lambda event: _user())
    monkeypatch.setattr(start, "_show_events", lambda max_user_id: False)
    monkeypatch.setattr(start, "_can_choose_address", lambda max_user_id: True)
    start.register_auth_commands(dp, bot)

    context = FakeContext()
    event = SimpleNamespace(chat_id=123, payload=None)
    asyncio.run(dp.handlers["bot_started"](event, context))
    asyncio.run(dp.handlers["message_created"](event, context))

    bot.send_message.assert_awaited_once()
    bot.edit_message.assert_not_awaited()


def test_two_explicit_starts_both_create_new_messages(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _bot()
    monkeypatch.setattr(start, "authorize_from_event", lambda event: _user())
    monkeypatch.setattr(start, "_show_events", lambda max_user_id: False)
    monkeypatch.setattr(start, "_can_choose_address", lambda max_user_id: True)
    start.register_auth_commands(dp, bot)

    context = FakeContext({"flow_mid": "old-mid"})
    event = SimpleNamespace(chat_id=123)
    asyncio.run(dp.handlers["message_created"](event, context))
    asyncio.run(dp.handlers["message_created"](event, context))

    assert bot.send_message.await_count == 2
    bot.edit_message.assert_not_awaited()


def test_welcome_explicit_recipient_for_notify_callback(monkeypatch) -> None:
    bot = _bot()
    monkeypatch.setattr(start, "_show_events", lambda max_user_id: False)
    monkeypatch.setattr(start, "_can_choose_address", lambda max_user_id: True)
    context = FakeContext({"flow_mid": "previous-message"})
    message = SimpleNamespace(answer=AsyncMock())
    event = SimpleNamespace(message=message)

    asyncio.run(start._render_welcome(bot, event, context, _user(), recipient_chat_id=54321))

    assert bot.send_message.await_args.kwargs["chat_id"] == 54321
    assert bot.send_message.await_args.kwargs["text"] == start.ADDRESS_PICKER_TEXT
    assert context.data == {"flow_mid": "welcome-mid"}
    message.answer.assert_not_awaited()
    bot.edit_message.assert_not_awaited()


def test_manage_addresses_is_a_mock_callback() -> None:
    dp = FakeDispatcher()
    start.register_auth_commands(dp, _bot())
    event = SimpleNamespace(ack=AsyncMock())
    asyncio.run(dp.handlers["message_callback"](event))
    event.ack.assert_awaited_once_with(notification="Управление адресами скоро появится")


def test_first_start_uses_first_image_only_once(monkeypatch) -> None:
    from project.bot_media import FIRST_START_IMAGE_PATH

    dp = FakeDispatcher()
    bot = _bot()
    seen = 0

    def authorize(_event):
        nonlocal seen
        seen += 1
        return _user(is_new=seen == 1)

    monkeypatch.setattr(start, "authorize_from_event", authorize)
    monkeypatch.setattr(start, "_show_events", lambda max_user_id: False)
    monkeypatch.setattr(start, "_can_choose_address", lambda max_user_id: True)
    start.register_auth_commands(dp, bot)
    event = SimpleNamespace(chat_id=123)
    asyncio.run(dp.handlers["message_created"](event, FakeContext()))
    first = bot.send_message.await_args.kwargs["attachments"]
    assert first[0].path == str(FIRST_START_IMAGE_PATH)
    asyncio.run(dp.handlers["message_created"](event, FakeContext()))
    second = bot.send_message.await_args.kwargs["attachments"]
    assert not any(getattr(item, "path", None) == str(FIRST_START_IMAGE_PATH) for item in second)
    assert bot.send_message.await_count == 2


def test_outsider_can_start_address_selection_but_not_open_news(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = _bot()
    monkeypatch.setattr(start, "authorize_from_event", lambda _event: _user(is_new=True))
    monkeypatch.setattr(start, "_show_events", lambda _max_id: False)
    monkeypatch.setattr(start, "_can_choose_address", lambda _max_id: True)
    monkeypatch.setattr(start, "send_home", AsyncMock())
    start.register_auth_commands(dp, bot)

    asyncio.run(dp.handlers["message_created"](SimpleNamespace(chat_id=123), FakeContext()))

    sent = bot.send_message.await_args.kwargs
    assert "Здравствуйте, Алексей!" in sent["text"]
    assert sent["attachments"][1].payload.buttons[0][0].text == "Указать свой адрес"
    assert all(
        button.text != "Смотреть события"
        for row in sent["attachments"][1].payload.buttons
        for button in row
    )
    start.send_home.assert_not_awaited()


def test_saved_address_needs_linked_chat_before_home(db_session, monkeypatch) -> None:
    from decimal import Decimal

    from address.db import AddressRow
    from auth.db import UserRow
    from auth.handlers.residence import set_personal_address
    from user_chat.handlers import add_user_to_chat, create_chat
    from user_chat.models import ChatCreate

    home = AddressRow(
        address_text="Москва, дом 1",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
    )
    db_session.add_all([home, UserRow(max_user_id=42)])
    db_session.flush()
    set_personal_address(db_session, max_user_id=42, address_id=home.id)

    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(start, "session_scope", same_session)
    assert start._can_choose_address(42)
    assert not start._show_events(42)

    chat = create_chat(db_session, ChatCreate(chat_id=-101, address_id=home.id))
    add_user_to_chat(db_session, chat.chat_id, max_user_id=42)
    from user_chat.handlers import set_member_address

    set_member_address(db_session, chat.chat_id, max_user_id=42, address_id=home.id)
    assert start._can_choose_address(42)
    assert start._show_events(42)
