"""Данные чатов: общий SQLite fixture проверяет настоящие внешние ключи."""

from __future__ import annotations

from decimal import Decimal

import pytest

from address.db import AddressRow
from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload
from user_chat.handlers import create_chat
from user_chat.models import ChatCreate


@pytest.fixture()
def address(db_session):
    row = AddressRow(
        address_text="Москва, улица Соседская, д. 1",
        latitude=Decimal("55.8123456"),
        longitude=Decimal("37.6123456"),
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def user(db_session):
    return authorize_user(db_session, MaxUserPayload(max_user_id=7, name="Сосед", username="test"))


@pytest.fixture()
def chat(db_session, address):
    return create_chat(
        db_session,
        ChatCreate(
            chat_id=-4_000_000_001,
            address_id=address.id,
            title="Чат дома",
            invite_link="https://max.ru/join/example",
        ),
    )
