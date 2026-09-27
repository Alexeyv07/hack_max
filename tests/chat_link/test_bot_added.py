from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import chat_link.commands.flow as flow
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

    def bot_removed(self, *args, **kwargs):
        return self._decorator("bot_removed")

    def user_added(self, *args, **kwargs):
        return self._decorator("user_added")

    def user_removed(self, *args, **kwargs):
        return self._decorator("user_removed")


def test_bot_added_uses_user_who_added_bot(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace()
    scheduled: list[tuple[int, int]] = []
    announce = AsyncMock()

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    registered = []
    monkeypatch.setattr(
        flow, "register_bot_group", lambda session, chat_id, **kw: registered.append((chat_id, kw))
    )
    monkeypatch.setattr(flow, "get_chat", lambda session, chat_id: None)
    monkeypatch.setattr(flow, "pending_for_actor", lambda session, user_id: None)
    monkeypatch.setattr(flow, "announce_group_address_setup", announce)
    monkeypatch.setattr(
        flow,
        "_schedule_added_group_connect",
        lambda bot, *, chat_id, actor_max_user_id: scheduled.append((chat_id, actor_max_user_id)),
    )
    flow.register_chat_link_commands(dp, bot)

    event = SimpleNamespace(
        chat_id=-100500,
        user=SimpleNamespace(user_id=321),
        is_channel=False,
    )
    asyncio.run(dp.handlers["bot_added"](event))

    announce.assert_awaited_once_with(bot, -100500)
    assert registered[0][0] == -100500
    assert registered[0][1]["actor_max_user_id"] == 321
    assert scheduled == []  # новая группа не привязывается без явного подтверждения


def test_bot_added_ignores_channels(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace()
    scheduled = []
    monkeypatch.setattr(
        flow,
        "_schedule_added_group_connect",
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )
    flow.register_chat_link_commands(dp, bot)

    event = SimpleNamespace(
        chat_id=-100500,
        user=SimpleNamespace(user_id=321),
        is_channel=True,
    )
    asyncio.run(dp.handlers["bot_added"](event))

    assert scheduled == []


def test_group_auto_connect_waits_for_bot_admin_rights(monkeypatch) -> None:
    ready = AsyncMock(side_effect=[False, True])
    connect = AsyncMock(
        return_value=ConnectOutcome(
            connected=True,
            chat_id=-100500,
            requester_added=True,
        )
    )
    sleep = AsyncMock()

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "bot_can_read_group", ready)
    monkeypatch.setattr(flow, "connect_added_group", connect)
    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(flow.asyncio, "sleep", sleep)

    announce = AsyncMock()
    monkeypatch.setattr(flow, "announce_connected_group", announce)
    monkeypatch.setattr(
        flow,
        "get_chat",
        lambda session, chat_id: SimpleNamespace(address_id=17),
    )
    monkeypatch.setattr(
        flow,
        "get_address_catalog",
        lambda: SimpleNamespace(get=lambda address_id: SimpleNamespace(address_text="Дом 17")),
    )
    bot = SimpleNamespace(
        me=SimpleNamespace(username="smart_city_bot"),
        send_message=AsyncMock(),
    )
    asyncio.run(
        flow._finish_added_group_when_ready(
            bot,
            chat_id=-100500,
            actor_max_user_id=321,
            attempts=2,
            delay=0,
        )
    )

    assert ready.await_count == 2
    sleep.assert_awaited_once_with(0)
    connect.assert_awaited_once()
    announce.assert_awaited_once_with(bot, -100500, requester_added=True, address_text="Дом 17")
    bot.send_message.assert_not_awaited()


def test_bot_removed_detaches_chat_and_cancels_pending_connect(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace()
    detached: list[int] = []

    @contextmanager
    def fake_session_scope():
        yield object()

    class FakeTask:
        def __init__(self) -> None:
            self.cancelled = False

        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            self.cancelled = True

    task = FakeTask()
    flow._GROUP_CONNECT_TASKS[-100500] = task
    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        flow,
        "deactivate_bot_group",
        lambda session, chat_id: detached.append(("inactive", chat_id)),
    )
    monkeypatch.setattr(
        flow,
        "detach_chat",
        lambda session, chat_id: detached.append(chat_id) or True,
    )
    flow.register_chat_link_commands(dp, bot)

    event = SimpleNamespace(
        chat_id=-100500,
        user=SimpleNamespace(user_id=321),
        is_channel=False,
    )
    asyncio.run(dp.handlers["bot_removed"](event))

    assert detached == [("inactive", -100500), -100500]
    assert task.cancelled
    assert -100500 not in flow._GROUP_CONNECT_TASKS


def test_connected_group_keyboard_has_only_personal_address_link() -> None:
    from chat_link.handlers.group import connected_group_keyboard

    bot = SimpleNamespace(me=SimpleNamespace(username="smart_city_bot"))
    buttons = connected_group_keyboard(bot, -100500).payload.buttons
    assert len(buttons) == 1
    assert len(buttons[0]) == 1
    assert buttons[0][0].text == "Указать свой адрес"
    assert "chat_-100500" in buttons[0][0].url
    assert "chat_bind_" not in buttons[0][0].url


def test_bot_added_reminds_when_not_admin(monkeypatch) -> None:
    from chat_link.handlers.group import announce_group_address_setup

    bot = SimpleNamespace(
        me=SimpleNamespace(username="smart_city_bot"),
        get_me_from_chat=AsyncMock(return_value=SimpleNamespace(is_admin=False, is_owner=False)),
        send_message=AsyncMock(),
    )
    asyncio.run(announce_group_address_setup(bot, -100500))
    text = bot.send_message.await_args.kwargs["text"]
    assert "пока не имеет необходимых прав" in text
    assert "Читать все сообщения" in text


def test_postal_input_ignores_group_message() -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock())
    flow.register_chat_link_commands(dp, bot)
    event = SimpleNamespace(
        chat_id=-100500,
        message=SimpleNamespace(
            recipient=SimpleNamespace(chat_type="chat", chat_id=-100500),
            body=SimpleNamespace(text="123456"),
        ),
    )
    asyncio.run(dp.handlers["message_created"](event, object()))
    bot.send_message.assert_not_awaited()
    bot.edit_message.assert_not_awaited()


def test_group_callback_cannot_open_private_picker() -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock())
    flow.register_chat_link_commands(dp, bot)
    event = SimpleNamespace(
        callback=SimpleNamespace(payload="chat_link:start", user=SimpleNamespace(user_id=321)),
        message=SimpleNamespace(recipient=SimpleNamespace(chat_type="chat", chat_id=-100500)),
        ack=AsyncMock(),
    )
    asyncio.run(dp.handlers["message_callback"](event, object()))
    event.ack.assert_awaited_once()
    bot.send_message.assert_not_awaited()


def test_bot_added_existing_chat_reminds_if_admin_rights_missing(monkeypatch) -> None:
    dp = FakeDispatcher()
    bot = SimpleNamespace()
    announced = AsyncMock()

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(flow, "register_bot_group", lambda *args, **kwargs: None)
    monkeypatch.setattr(flow, "get_chat", lambda *args: SimpleNamespace(chat_type="chat"))
    monkeypatch.setattr(flow, "pending_for_actor", lambda *args: None)
    monkeypatch.setattr(flow, "bot_can_read_group", AsyncMock(return_value=False))
    monkeypatch.setattr(flow, "announce_group_address_setup", announced)
    flow.register_chat_link_commands(dp, bot)
    event = SimpleNamespace(chat_id=-100500, user=SimpleNamespace(user_id=321), is_channel=False)
    asyncio.run(dp.handlers["bot_added"](event))
    announced.assert_awaited_once_with(bot, -100500)
