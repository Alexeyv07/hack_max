"""Главная после выбора адреса: реальные привязки и одна отправка с фото."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from address.db import AddressRow
from auth.commands.home import (
    HOME_IMAGE_PATH,
    build_home_keyboard,
    build_home_text,
    linked_addresses,
    send_home,
)
from auth.db import UserRow
from user_chat.db import ChatRow, chat_addresses, users_chat


def test_home_lists_only_member_selected_addresses(db_session) -> None:
    selected = AddressRow(
        address_text="Москва, улица <Мира>, д. 1",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
    )
    unselected = AddressRow(
        address_text="Москва, улица Мира, д. 2",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
    )
    member = UserRow(max_user_id=42, chat_id=1000)
    stranger = UserRow(max_user_id=43, chat_id=2000)
    db_session.add_all([selected, unselected, member, stranger])
    db_session.flush()
    chat = ChatRow(chat_id=-7, title="Домовой чат", address_id=selected.id, chat_type="chat")
    db_session.add(chat)
    db_session.flush()
    db_session.execute(chat_addresses.insert().values(chat_id=-7, address_id=selected.id))
    db_session.execute(chat_addresses.insert().values(chat_id=-7, address_id=unselected.id))
    db_session.execute(
        users_chat.insert().values(user_id=member.id, chat_id=-7, address_id=selected.id)
    )
    assert linked_addresses(db_session, 42) == [selected.address_text]
    assert linked_addresses(db_session, 43) == []
    text = build_home_text(linked_addresses(db_session, 42))
    assert text.startswith("<b>Главная</b>")
    assert "&lt;Мира&gt;" in text
    assert unselected.address_text not in text
    assert "Посмотреть новости рядом" in text or "новости" in text.casefold()


def test_home_keyboard_matches_mockup() -> None:
    bot = SimpleNamespace(me=SimpleNamespace(username="bot", user_id=7))
    keyboard = build_home_keyboard(bot)
    buttons = keyboard.payload.buttons
    assert [row[0].text for row in buttons] == [
        "Посмотреть новости рядом",
        "Управлять адресами",
    ]
    assert buttons[1][0].payload == "home:manage"
    assert buttons[0][0].web_app == "bot"
    assert "справка о сервисе" in build_home_text([])
    assert "<a href=" in build_home_text([])


def test_home_sends_image_and_keyboard_together(db_session) -> None:
    user = UserRow(max_user_id=42, chat_id=1000)
    db_session.add(user)
    db_session.flush()
    bot = SimpleNamespace(
        me=SimpleNamespace(username="bot", user_id=7),
        send_message=AsyncMock(),
    )
    assert HOME_IMAGE_PATH.is_file()
    asyncio.run(send_home(bot, db_session, 42))
    bot.send_message.assert_awaited_once()
    sent = bot.send_message.await_args.kwargs
    assert sent["chat_id"] == 1000
    assert "Ваши адреса 🏠" in sent["text"]
    assert sent["text"].startswith("<b>Главная</b>")
    assert "—" in sent["text"]
    assert len(sent["attachments"]) == 2
    assert sent["attachments"][0].type == "image"
    assert sent["attachments"][1].payload.buttons[1][0].payload == "home:manage"


def test_home_falls_back_to_text_when_upload_fails(db_session) -> None:
    user = UserRow(max_user_id=42, chat_id=1000)
    db_session.add(user)
    db_session.flush()
    bot = SimpleNamespace(
        me=SimpleNamespace(username="bot", user_id=7),
        send_message=AsyncMock(side_effect=[RuntimeError("image upload failed"), None]),
    )
    asyncio.run(send_home(bot, db_session, 42))
    assert bot.send_message.await_count == 2
    assert len(bot.send_message.await_args.kwargs["attachments"]) == 1


def test_home_does_not_show_old_personal_address_without_chat(db_session) -> None:
    from auth.handlers.residence import set_personal_address

    home = AddressRow(
        address_text="Москва, новый дом",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
    )
    db_session.add_all([home, UserRow(max_user_id=1001)])
    db_session.flush()
    set_personal_address(db_session, max_user_id=1001, address_id=home.id)
    assert linked_addresses(db_session, 1001) == []
    assert home.address_text not in build_home_text(linked_addresses(db_session, 1001))
