"""Создание и поиск чатов по MAX id и surrogate id адреса."""

from __future__ import annotations

import pytest

from user_chat.db import ChatRow
from user_chat.handlers import create_chat, get_chat, list_chats_by_address
from user_chat.models import ChatCreate


def test_create_and_get_chat(db_session, chat, address) -> None:
    assert get_chat(db_session, chat.chat_id) == chat
    assert chat.chat_id == -4_000_000_001
    assert chat.invite_link == "https://max.ru/join/example"
    row = db_session.get(ChatRow, chat.chat_id)
    assert row.address_id == address.id
    assert row.address is address
    assert row.users == []
    assert "latitude" not in ChatRow.__table__.columns
    assert "address_text" not in ChatRow.__table__.columns


def test_multiple_chats_for_same_address(db_session, chat, address) -> None:
    other = create_chat(db_session, ChatCreate(chat_id=4_000_000_001, address_id=address.id))
    assert other.invite_link is None
    assert list_chats_by_address(db_session, address.id) == [chat, other]
    assert list_chats_by_address(db_session, address.id + 1) == []
    assert get_chat(db_session, 999) is None


def test_duplicate_chat_is_rejected(db_session, chat, address) -> None:
    with pytest.raises(ValueError, match="уже существует"):
        create_chat(db_session, ChatCreate(chat_id=chat.chat_id, address_id=address.id))


def test_unknown_address_is_rejected(db_session) -> None:
    with pytest.raises(ValueError, match="Адрес.*не найден"):
        create_chat(db_session, ChatCreate(chat_id=1, address_id=999))


@pytest.mark.parametrize("chat_id", [True, "42", 2**63, -(2**63) - 1])
def test_invalid_max_chat_id(db_session, address, chat_id) -> None:
    with pytest.raises(ValueError, match="64-битным"):
        create_chat(db_session, ChatCreate(chat_id=chat_id, address_id=address.id))


@pytest.mark.parametrize("fields", [{"title": " "}, {"title": "x" * 256}, {"invite_link": " "}])
def test_invalid_chat_text(db_session, address, fields) -> None:
    with pytest.raises(ValueError):
        create_chat(db_session, ChatCreate(chat_id=1, address_id=address.id, **fields))
