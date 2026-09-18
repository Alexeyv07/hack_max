"""Бизнес-flow KAN-7 без MAX API."""

from __future__ import annotations

from decimal import Decimal

import pytest

from address.db import AddressRow
from auth.handlers.authorize import authorize_user
from auth.models import MaxUserPayload
from chat_link.db import ChatLinkRow
from chat_link.handlers import (
    bind_chat_link,
    connect_by_address,
    connect_by_token,
    connect_to_chat,
    create_chat_link,
)
from chat_link.models import ChatLinkStatus
from user_chat.handlers import create_chat, list_memberships_for_user
from user_chat.models import ChatCreate


def _address(db_session, *, text="Москва, Тестовая улица, д. 1"):
    row = AddressRow(
        address_text=text,
        postal_code="123456",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
        is_private=False,
        city="Москва",
        street="Тестовая улица",
        house="1",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _user(db_session, max_user_id=101):
    return authorize_user(db_session, MaxUserPayload(max_user_id=max_user_id, name="Сосед"))


def test_existing_chat_is_auto_approved(db_session) -> None:
    address = _address(db_session)
    user = _user(db_session)
    chat = create_chat(db_session, ChatCreate(chat_id=500, address_id=address.id))

    result = connect_by_address(
        db_session,
        max_user_id=user.max_user_id,
        user_input=address.address_text,
    )

    assert result.chat_ids == (chat.chat_id,)
    assert result.joined_chat_id == chat.chat_id
    assert list_memberships_for_user(db_session, user.max_user_id)[0].chat_id == chat.chat_id


def test_multiple_chats_require_explicit_choice(db_session) -> None:
    address = _address(db_session)
    user = _user(db_session)
    create_chat(db_session, ChatCreate(chat_id=500, address_id=address.id))
    create_chat(db_session, ChatCreate(chat_id=501, address_id=address.id))

    result = connect_by_address(
        db_session,
        max_user_id=user.max_user_id,
        user_input=address.address_text,
    )
    assert result.needs_chat_choice
    assert result.chat_ids == (500, 501)
    assert list_memberships_for_user(db_session, user.max_user_id) == []

    connect_to_chat(db_session, max_user_id=user.max_user_id, chat_id=501)
    assert [item.chat_id for item in list_memberships_for_user(db_session, user.max_user_id)] == [
        501
    ]


def test_no_chat_moves_flow_to_admin_question(db_session) -> None:
    address = _address(db_session)
    user = _user(db_session)
    result = connect_by_address(
        db_session,
        max_user_id=user.max_user_id,
        user_input=address.address_text,
    )
    assert result.address_id == address.id
    assert result.needs_new_chat
    assert result.joined_chat_id is None


def test_admin_and_non_admin_create_different_pending_states(db_session) -> None:
    address = _address(db_session)
    admin = _user(db_session, 101)
    neighbor = _user(db_session, 202)

    admin_link = create_chat_link(
        db_session,
        address_id=address.id,
        max_user_id=admin.max_user_id,
        is_admin=True,
    )
    neighbor_link = create_chat_link(
        db_session,
        address_id=address.id,
        max_user_id=neighbor.max_user_id,
        is_admin=False,
    )
    assert admin_link.status is ChatLinkStatus.PENDING_BOT
    assert neighbor_link.status is ChatLinkStatus.PENDING_ADMIN


def test_new_request_cancels_previous_pending_for_same_user(db_session) -> None:
    address = _address(db_session)
    user = _user(db_session)
    first = create_chat_link(
        db_session,
        address_id=address.id,
        max_user_id=user.max_user_id,
        is_admin=True,
    )
    second = create_chat_link(
        db_session,
        address_id=address.id,
        max_user_id=user.max_user_id,
        is_admin=False,
    )
    assert db_session.get(ChatLinkRow, first.token).status == ChatLinkStatus.CANCELLED.value
    assert db_session.get(ChatLinkRow, second.token).status == ChatLinkStatus.PENDING_ADMIN.value


def test_bind_auto_approves_creator_and_token_can_join_neighbor(db_session) -> None:
    address = _address(db_session)
    creator = _user(db_session, 101)
    neighbor = _user(db_session, 202)
    link = create_chat_link(
        db_session,
        address_id=address.id,
        max_user_id=creator.max_user_id,
        is_admin=False,
    )

    chat = bind_chat_link(
        db_session,
        token=link.token,
        chat_id=-777,
        title="Наш дом",
        invite_link="https://max.ru/example",
    )
    stored = db_session.get(ChatLinkRow, link.token)
    assert stored.status == ChatLinkStatus.READY.value
    assert stored.chat_id == chat.chat_id
    assert list_memberships_for_user(db_session, creator.max_user_id)[0].chat_id == -777

    joined = connect_by_token(db_session, token=link.token, max_user_id=neighbor.max_user_id)
    assert joined.chat_id == -777
    assert list_memberships_for_user(db_session, neighbor.max_user_id)[0].chat_id == -777


def test_pending_token_cannot_join(db_session) -> None:
    address = _address(db_session)
    user = _user(db_session)
    link = create_chat_link(
        db_session,
        address_id=address.id,
        max_user_id=user.max_user_id,
        is_admin=False,
    )
    with pytest.raises(ValueError, match="ещё не подключён"):
        connect_by_token(db_session, token=link.token, max_user_id=user.max_user_id)
