"""Раздельное управление личными адресами и адресами MAX-групп."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from maxapi.enums import ChatType
from sqlalchemy import select

import auth.commands.manage_chats as commands
from address.db import AddressRow
from auth.db import UserRow
from chat_link.db import BotGroupRow
from chat_link.handlers.registry import AdminGroup, connected_admin_groups
from user_chat.db import ChatRow, chat_addresses
from user_chat.handlers import list_chat_addresses


def _fixture_data(session):
    first = AddressRow(
        address_text="Москва, Сельскохозяйственная улица, д. 15 с3",
        latitude=Decimal("55.7"),
        longitude=Decimal("37.6"),
    )
    second = AddressRow(
        address_text="Москва, Сельскохозяйственная улица, д. 15 к1",
        latitude=Decimal("55.7"),
        longitude=Decimal("37.6"),
    )
    session.add_all([first, second, UserRow(max_user_id=42, chat_id=420)])
    session.flush()
    session.add(ChatRow(chat_id=-123, title="Тестовый чат", address_id=first.id, chat_type="chat"))
    session.add(BotGroupRow(chat_id=-123, title="Тестовый чат", is_active=True))
    session.add(BotGroupRow(chat_id=-124, title="Ещё не подключён", is_active=True))
    session.flush()
    session.execute(
        chat_addresses.insert(),
        [
            {"chat_id": -123, "address_id": first.id},
            {"chat_id": -123, "address_id": second.id},
        ],
    )
    return first, second


def _bot():
    return SimpleNamespace(
        get_chat_by_id=AsyncMock(
            return_value=SimpleNamespace(type=ChatType.CHAT, title="Тестовый чат", link=None)
        ),
        get_chat_member=AsyncMock(return_value=SimpleNamespace(is_admin=True, is_owner=False)),
        get_me_from_chat=AsyncMock(
            return_value=SimpleNamespace(
                is_admin=True, is_owner=False, permissions=["read_all_messages"]
            )
        ),
        edit_message=AsyncMock(),
        send_message=AsyncMock(),
        me=SimpleNamespace(username="bot", user_id=1),
    )


def test_only_connected_admin_chats_are_listed(db_session):
    _fixture_data(db_session)
    bot = _bot()
    groups = asyncio.run(connected_admin_groups(bot, db_session, max_user_id=42))
    assert [(item.chat_id, item.title) for item in groups] == [(-123, "Тестовый чат")]
    bot.get_chat_member.return_value.is_admin = False
    assert asyncio.run(connected_admin_groups(bot, db_session, max_user_id=42)) == []
    bot.get_chat_member.return_value.is_admin = True
    bot.get_me_from_chat.return_value.permissions = []
    assert asyncio.run(connected_admin_groups(bot, db_session, max_user_id=42)) == []


def test_chats_list_address_selection_and_back():
    group = AdminGroup(chat_id=-123, title="Наш чат")
    text, keyboard = commands.chat_list_view([group])
    assert "Выбор чатов" in text
    assert keyboard.payload.buttons[0][0].payload == "home:chats:open:-123"
    assert keyboard.payload.buttons[-2][0].text == "Привязать чат"
    assert keyboard.payload.buttons[-2][0].payload == "chat_link:start:admin"
    assert keyboard.payload.buttons[-1][0].payload == "home:addresses:home"

    addresses = [SimpleNamespace(id=42, address_text="Москва, ул. Длинная, д. 15 корп. 1")]
    text, keyboard = commands.chat_addresses_view(group, addresses)
    assert "Наш чат" in text
    assert keyboard.payload.buttons[0][0].payload == "home:chats:address:-123:42"
    assert keyboard.payload.buttons[1][0].payload == "chat_link:start:chat:-123"
    assert keyboard.payload.buttons[-1][0].payload == "home:chats"
    detail, keyboard = commands.chat_address_view(group, addresses[0])
    assert addresses[0].address_text in detail
    assert keyboard.payload.buttons[0][0].payload == "home:chats:delete:-123:42"
    assert keyboard.payload.buttons[-1][0].payload == "home:chats:open:-123"


def test_delete_group_address_preserves_other_and_user_personal(db_session, monkeypatch):
    first, second = _fixture_data(db_session)
    bot = _bot()

    @contextmanager
    def same_session():
        yield db_session
        db_session.flush()

    monkeypatch.setattr(commands, "session_scope", same_session)
    announce = AsyncMock()
    monkeypatch.setattr(commands, "announce_connected_group", announce)
    monkeypatch.setattr(commands, "has_connected_admin_chats", AsyncMock(return_value=True))
    show = AsyncMock()
    event = SimpleNamespace(ack=AsyncMock())
    asyncio.run(
        commands.handle_manage_chats(bot, event, 42, f"home:chats:delete:-123:{first.id}", show)
    )
    assert [row.id for row in list_chat_addresses(db_session, -123)] == [second.id]
    assert db_session.get(ChatRow, -123).address_id == second.id
    assert db_session.scalar(select(UserRow).where(UserRow.max_user_id == 42)).address_id is None
    announce.assert_awaited_once_with(bot, -123)
    assert "Адрес успешно удалён из чата" in show.await_args.args[3]
    assert show.await_args.args[4][1].payload.buttons[0][0].text == "Мои адреса"


def test_last_address_unlinks_group_without_removing_bot(db_session, monkeypatch):
    first, second = _fixture_data(db_session)
    bot = _bot()
    # Сначала убираем второй адрес и проверяем удаление последнего.
    from user_chat.handlers import remove_chat_address

    assert remove_chat_address(db_session, -123, second.id)

    @contextmanager
    def same_session():
        yield db_session
        db_session.flush()

    monkeypatch.setattr(commands, "session_scope", same_session)
    announce = AsyncMock()
    monkeypatch.setattr(commands, "announce_unlinked_group", announce)
    monkeypatch.setattr(commands, "has_connected_admin_chats", AsyncMock(return_value=False))
    show = AsyncMock()
    asyncio.run(
        commands.handle_manage_chats(
            bot, SimpleNamespace(ack=AsyncMock()), 42, f"home:chats:delete:-123:{first.id}", show
        )
    )
    assert list_chat_addresses(db_session, -123) == []
    assert db_session.get(ChatRow, -123).chat_type == "removed"
    assert db_session.get(BotGroupRow, -123).is_active  # Бот остаётся в MAX-группе.
    announce.assert_awaited_once_with(bot, -123)
    assert "Адрес успешно удалён из чата" in show.await_args.args[3]
    assert all(
        row[0].text != "Администрирование чатов"
        for row in show.await_args.args[4][1].payload.buttons
    )


def test_rebind_group_after_last_address_was_removed(db_session):
    from chat_link.handlers.group import connect_added_group_to_address
    from user_chat.handlers import remove_chat_address

    first, second = _fixture_data(db_session)
    assert remove_chat_address(db_session, -123, second.id)
    assert remove_chat_address(db_session, -123, first.id)
    assert db_session.get(ChatRow, -123).chat_type == "removed"
    result = asyncio.run(
        connect_added_group_to_address(
            _bot(), db_session, chat_id=-123, admin_max_user_id=42, address_id=second.id
        )
    )
    assert result.connected
    assert db_session.get(ChatRow, -123).chat_type == "chat"
    assert db_session.get(ChatRow, -123).address_id == second.id
    assert [row.id for row in list_chat_addresses(db_session, -123)] == [second.id]
