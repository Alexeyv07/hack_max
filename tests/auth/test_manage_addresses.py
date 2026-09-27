"""KAN-32: личные адреса без изменения общего домового чата."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import auth.commands.manage_addresses as commands
from address.db import AddressRow
from auth.commands.home import linked_addresses
from auth.db import UserRow
from auth.handlers.managed_addresses import list_managed_addresses, remove_managed_address
from user_chat.db import ChatRow, chat_addresses, users_chat
from user_chat.handlers.membership import has_connected_chat


def _address(text: str) -> AddressRow:
    return AddressRow(
        address_text=text, latitude=Decimal("55.7500000"), longitude=Decimal("37.6100000")
    )


def _setup(db_session):
    a = _address("Москва, ул. Первая, д. 1")
    b = _address("Москва, ул. Вторая, д. 2")
    shared = _address("Москва, ул. Третья, д. 3")
    user = UserRow(max_user_id=42, chat_id=420)
    neighbor = UserRow(max_user_id=43, chat_id=430)
    db_session.add_all([a, b, shared, user, neighbor])
    db_session.flush()
    user.address_id = a.id
    db_session.add_all(
        [
            ChatRow(chat_id=-1, title="Дом 1", address_id=a.id, chat_type="chat"),
            ChatRow(chat_id=-2, title="Дом 2", address_id=b.id, chat_type="chat"),
        ]
    )
    db_session.flush()
    db_session.execute(
        chat_addresses.insert(),
        [
            {"chat_id": -1, "address_id": a.id},
            {"chat_id": -1, "address_id": shared.id},
            {"chat_id": -2, "address_id": b.id},
        ],
    )
    db_session.execute(
        users_chat.insert(),
        [
            {"chat_id": -1, "user_id": user.id, "address_id": a.id},
            {"chat_id": -2, "user_id": user.id, "address_id": b.id},
            {"chat_id": -1, "user_id": neighbor.id, "address_id": a.id},
        ],
    )
    return a, b, shared, user, neighbor


def test_list_only_owned_addresses_without_shared_chat_addresses(db_session) -> None:
    a, b, shared, _, _ = _setup(db_session)
    assert [(item.id, item.text) for item in list_managed_addresses(db_session, 42)] == [
        (b.id, b.address_text),
        (a.id, a.address_text),
    ]
    assert list_managed_addresses(db_session, 43)[0].id == a.id
    assert [(item.text, item.chat_titles) for item in list_managed_addresses(db_session, 42)] == [
        (b.address_text, ("Дом 2",)),
        (a.address_text, ("Дом 1",)),
    ]
    assert shared.address_text not in linked_addresses(db_session, 42)
    assert list_managed_addresses(db_session, 999) == []


def test_remove_selected_address_preserves_membership_group_and_other_user(db_session) -> None:
    a, b, shared, user, neighbor = _setup(db_session)
    assert remove_managed_address(db_session, max_user_id=42, address_id=a.id)
    assert user.address_id == b.id
    assert has_connected_chat(db_session, 42)
    assert [item.id for item in list_managed_addresses(db_session, 42)] == [b.id]
    assert (
        db_session.scalar(
            users_chat.select()
            .with_only_columns(users_chat.c.address_id)
            .where(users_chat.c.user_id == user.id, users_chat.c.chat_id == -1)
        )
        is None
    )
    assert (
        db_session.scalar(
            users_chat.select()
            .with_only_columns(users_chat.c.address_id)
            .where(users_chat.c.user_id == neighbor.id, users_chat.c.chat_id == -1)
        )
        == a.id
    )
    assert set(
        db_session.scalars(chat_addresses.select().with_only_columns(chat_addresses.c.address_id))
    ) == {a.id, b.id, shared.id}
    assert not remove_managed_address(db_session, max_user_id=42, address_id=a.id)
    assert not remove_managed_address(db_session, max_user_id=42, address_id=shared.id)


def test_remove_last_address_keeps_chat_membership(db_session) -> None:
    a, b, _, user, _ = _setup(db_session)
    assert remove_managed_address(db_session, max_user_id=42, address_id=b.id)
    assert remove_managed_address(db_session, max_user_id=42, address_id=a.id)
    assert user.address_id is None
    assert not has_connected_chat(db_session, 42)
    assert list_managed_addresses(db_session, 42) == []
    assert (
        db_session.scalar(
            users_chat.select()
            .with_only_columns(users_chat.c.user_id)
            .where(users_chat.c.user_id == user.id, users_chat.c.chat_id == -1)
        )
        == user.id
    )


def test_foreign_user_cannot_remove_someone_elses_address(db_session) -> None:
    _, b, _, _, _ = _setup(db_session)
    assert not remove_managed_address(db_session, max_user_id=43, address_id=b.id)
    assert not remove_managed_address(db_session, max_user_id=999, address_id=b.id)
    assert b.id in [row.id for row in list_managed_addresses(db_session, 42)]


class FakeDispatcher:
    def __init__(self) -> None:
        self.callback = None

    def message_callback(self, *_args, **_kwargs):
        def decorator(func):
            self.callback = func
            return func

        return decorator


def _event(payload: str):
    return SimpleNamespace(
        callback=SimpleNamespace(payload=payload, user=SimpleNamespace(user_id=42)),
        message=SimpleNamespace(body=SimpleNamespace(mid="manage-mid")),
        ack=AsyncMock(),
        edit=AsyncMock(),
    )


def test_management_flow_list_detail_back_delete(db_session, monkeypatch) -> None:
    a, b, _, user, _ = _setup(db_session)

    @contextmanager
    def fake_session_scope():
        yield db_session

    monkeypatch.setattr(commands, "session_scope", fake_session_scope)
    dp = FakeDispatcher()
    bot = SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock())
    commands.register_manage_addresses(dp, bot)

    event = _event("home:manage")
    asyncio.run(dp.callback(event))
    event.edit.assert_awaited_once()
    bot.send_message.assert_not_awaited()
    attachments = event.edit.await_args.kwargs["attachments"]
    assert len(attachments) == 2
    assert getattr(attachments[0], "type", None) == "image" or "other_messages" in str(
        getattr(attachments[0], "path", "")
        or getattr(getattr(attachments[0], "payload", None), "token", "")
    )
    markup = attachments[1].payload.buttons
    assert [row[0].text for row in markup[:2]] == [b.address_text, a.address_text]
    assert markup[0][0].payload == f"home:addresses:open:{b.id}:0"
    assert markup[2][0].text == "Добавить адрес"
    assert markup[2][0].payload == "chat_link:start:manage"
    assert markup[3][0].text == "Назад"
    assert markup[3][0].payload == "home:addresses:home"

    event = _event(f"home:addresses:open:{a.id}:0")
    asyncio.run(dp.callback(event))
    detail = event.edit.await_args.kwargs
    assert a.address_text in detail["text"]
    assert "Дом 1" in detail["text"]
    assert "Привязка дома к групповому чату" not in detail["text"]
    assert [row[0].text for row in detail["attachments"][1].payload.buttons] == [
        "Удалить адрес",
        "Назад",
    ]
    assert detail["attachments"][1].payload.buttons[1][0].payload == "home:addresses:list:0"

    event = _event("home:addresses:list:0")
    asyncio.run(dp.callback(event))
    assert "Ваши адреса" in event.edit.await_args.kwargs["text"]

    event = _event(f"home:addresses:delete:{a.id}:0")
    asyncio.run(dp.callback(event))
    assert "✅ Адрес успешно удалён." in event.edit.await_args.kwargs["text"]
    assert [
        row[0].text for row in event.edit.await_args.kwargs["attachments"][1].payload.buttons
    ] == ["На главную"]
    assert (
        event.edit.await_args.kwargs["attachments"][1].payload.buttons[0][0].payload
        == "home:addresses:home"
    )
    assert user.address_id == b.id
    assert len(list_managed_addresses(db_session, 42)) == 1

    event = _event(f"home:addresses:delete:{a.id}:0")
    asyncio.run(dp.callback(event))
    assert "уже удалён" in event.edit.await_args.kwargs["text"]

    event = _event("home:addresses:home")
    asyncio.run(dp.callback(event))
    assert event.edit.await_args.kwargs["text"].startswith("<b>Главная</b>")


def test_list_pagination_and_escaped_html() -> None:
    addresses = [commands.ManagedAddress(i, f"Дом <{i}>") for i in range(1, 19)]
    text, keyboard = commands._list_view(addresses, 1)
    assert "Ваши адреса" in text
    buttons = keyboard.payload.buttons
    assert len(buttons) == 11  # 8 адресов, навигация, добавить и назад
    assert buttons[0][0].payload == "home:addresses:open:9:1"
    assert [button.text for button in buttons[8]] == ["‹", "2/3", "›"]
    assert buttons[9][0].text == "Добавить адрес"
    assert buttons[9][0].payload == "chat_link:start:manage"
    assert buttons[10][0].text == "Назад"
    detail_text, detail_keyboard = commands._detail_view(addresses[0], 0)
    assert "&lt;1&gt;" in detail_text
    assert detail_keyboard.payload.buttons[0][0].payload == "home:addresses:delete:1:0"


def test_empty_list_allows_selecting_address_again() -> None:
    text, keyboard = commands._list_view([], 0)
    assert "Пока нет сохранённых адресов" in text
    assert keyboard.payload.buttons[0][0].text == "Добавить адрес"
    assert keyboard.payload.buttons[0][0].payload == "chat_link:start:manage"
    assert keyboard.payload.buttons[1][0].text == "Назад"
    assert keyboard.payload.buttons[1][0].payload == "home:addresses:home"


def test_details_show_every_chat_for_the_same_address(db_session) -> None:
    a, _, _, user, _ = _setup(db_session)
    db_session.add(ChatRow(chat_id=-3, title="Второй <чат>", address_id=a.id, chat_type="chat"))
    db_session.flush()
    db_session.execute(chat_addresses.insert().values(chat_id=-3, address_id=a.id))
    db_session.execute(users_chat.insert().values(user_id=user.id, chat_id=-3, address_id=a.id))

    addresses = list_managed_addresses(db_session, 42)
    assert len(addresses) == 2  # повторный адрес не создаёт вторую кнопку
    detail_text, _ = commands._detail_view(next(item for item in addresses if item.id == a.id), 0)
    assert "Дом 1" in detail_text
    assert "Второй &lt;чат&gt;" in detail_text
    assert "<b>Чаты:</b>" in detail_text


def test_personal_address_fallback_shows_linked_chat(db_session) -> None:
    a, _, shared, user, _ = _setup(db_session)
    user.address_id = shared.id
    db_session.flush()

    addresses = list_managed_addresses(db_session, 42)
    assert next(item for item in addresses if item.id == shared.id).chat_titles == ("Дом 1",)
    assert a.id in [item.id for item in addresses]
