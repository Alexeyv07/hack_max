"""Реальные связи User <-> Chat и проекция координат для событий."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from address.db import AddressRow
from auth.db import UserRow
from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload
from user_chat.db import ChatRow, users_chat
from user_chat.handlers import (
    add_chat_address,
    add_user_to_chat,
    create_chat,
    detach_chat,
    has_connected_chat,
    list_chat_members,
    list_memberships_for_user,
    remove_user_from_chat,
    set_member_address,
)
from user_chat.models import ChatCreate


def test_memberships_empty_without_user(db_session) -> None:
    assert list_memberships_for_user(db_session, max_user_id=1) == []


def test_registration_does_not_add_membership(db_session, chat) -> None:
    # auth.chat_id — контекст входа в бота, не доказательство членства в доме.
    authorize_user(db_session, MaxUserPayload(max_user_id=7, chat_id=chat.chat_id))
    assert list_memberships_for_user(db_session, max_user_id=7) == []
    assert list_chat_members(db_session, chat.chat_id) == []


def test_legacy_dialog_membership_does_not_unlock_events(db_session, address, user) -> None:
    legacy = ChatRow(
        chat_id=777,
        address_id=address.id,
        title="Старый DIALOG mock",
        chat_type=None,
    )
    db_session.add(legacy)
    db_session.flush()
    assert add_user_to_chat(db_session, legacy.chat_id, max_user_id=user.max_user_id)

    assert not has_connected_chat(db_session, user.max_user_id)
    assert list_memberships_for_user(db_session, user.max_user_id) == []


def test_users_and_chats_are_many_to_many(db_session, chat, address, user) -> None:
    other_user = authorize_user(db_session, MaxUserPayload(max_user_id=8, name="Другой"))
    other_chat = create_chat(db_session, ChatCreate(chat_id=42, address_id=address.id))
    assert add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    assert add_user_to_chat(db_session, chat.chat_id, max_user_id=other_user.max_user_id)
    assert add_user_to_chat(db_session, other_chat.chat_id, max_user_id=user.max_user_id)
    set_member_address(db_session, chat.chat_id, max_user_id=7, address_id=address.id)
    set_member_address(db_session, other_chat.chat_id, max_user_id=7, address_id=address.id)
    set_member_address(db_session, chat.chat_id, max_user_id=8, address_id=address.id)
    assert {member.user_id for member in list_chat_members(db_session, chat.chat_id)} == {
        user.id,
        other_user.id,
    }
    assert [member.max_user_id for member in list_chat_members(db_session, other_chat.chat_id)] == [
        7
    ]
    assert {item.chat_id for item in list_memberships_for_user(db_session, 7)} == {chat.chat_id, 42}
    assert [item.chat_id for item in list_memberships_for_user(db_session, 8)] == [chat.chat_id]
    assert list_chat_members(db_session, 999) == []


def test_repeat_membership_is_idempotent(db_session, chat, user) -> None:
    row = db_session.get(ChatRow, chat.chat_id)
    assert row.users == []
    assert add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    assert len(row.users) == 1
    assert not add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    assert len(list_chat_members(db_session, chat.chat_id)) == 1
    another = authorize_user(db_session, MaxUserPayload(max_user_id=9))
    assert add_user_to_chat(db_session, chat.chat_id, max_user_id=another.max_user_id)


def test_membership_requires_registered_user_and_existing_chat(db_session, chat, user) -> None:
    with pytest.raises(ValueError, match="не зарегистрирован"):
        add_user_to_chat(db_session, chat.chat_id, max_user_id=999)
    with pytest.raises(ValueError, match="не найден"):
        add_user_to_chat(db_session, 999, max_user_id=user.max_user_id)
    assert db_session.scalar(select(users_chat.c.user_id)) is None


def test_remove_membership_keeps_other_chat_and_parents(db_session, chat, address, user) -> None:
    create_chat(db_session, ChatCreate(chat_id=42, address_id=address.id))
    add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    add_user_to_chat(db_session, 42, max_user_id=user.max_user_id)
    assert remove_user_from_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    assert not remove_user_from_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    assert not remove_user_from_chat(db_session, 999, max_user_id=user.max_user_id)
    assert not remove_user_from_chat(db_session, 42, max_user_id=999)
    assert list_chat_members(db_session, chat.chat_id) == []
    assert len(list_chat_members(db_session, 42)) == 1
    assert db_session.get(UserRow, user.id) is not None
    assert db_session.get(ChatRow, chat.chat_id) is not None
    assert db_session.get(AddressRow, address.id) is not None


def test_membership_reads_current_address_coordinates(db_session, chat, address, user) -> None:
    add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    set_member_address(
        db_session, chat.chat_id, max_user_id=user.max_user_id, address_id=address.id
    )
    membership = list_memberships_for_user(db_session, user.max_user_id)[0]
    assert membership.chat_id == chat.chat_id
    assert membership.title == chat.title
    assert membership.lat == float(address.latitude)
    assert membership.lon == float(address.longitude)
    address.latitude = Decimal("56.1234567")
    db_session.flush()
    assert list_memberships_for_user(db_session, user.max_user_id)[0].lat == 56.1234567


def test_handlers_leave_transaction_to_caller(db_session, chat, user) -> None:
    add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    db_session.rollback()
    assert db_session.get(ChatRow, chat.chat_id) is None
    assert db_session.scalar(select(users_chat.c.user_id)) is None


def test_detach_chat_marks_removed_and_clears_memberships(db_session, chat, address, user) -> None:
    add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    set_member_address(
        db_session, chat.chat_id, max_user_id=user.max_user_id, address_id=address.id
    )
    assert has_connected_chat(db_session, user.max_user_id)

    assert detach_chat(db_session, chat.chat_id)

    row = db_session.get(ChatRow, chat.chat_id)
    assert row is not None
    assert row.chat_type == "removed"
    assert row.invite_link is None
    assert list_chat_members(db_session, chat.chat_id) == []
    assert list_memberships_for_user(db_session, user.max_user_id) == []
    assert not has_connected_chat(db_session, user.max_user_id)


def test_courtyard_chat_members_select_separate_addresses(db_session, chat, address, user) -> None:
    """Один MAX-чат, два дома, два собственных адреса без подмены друг друга."""
    second = AddressRow(
        address_text="Москва, улица Соседская, д. 2",
        latitude=Decimal("55.8124000"),
        longitude=Decimal("37.6124000"),
    )
    foreign = AddressRow(
        address_text="Москва, улица Соседская, д. 3",
        latitude=Decimal("55.8130000"),
        longitude=Decimal("37.6130000"),
    )
    db_session.add_all([second, foreign])
    db_session.flush()
    assert add_chat_address(db_session, chat.chat_id, second.id)
    assert not add_chat_address(db_session, chat.chat_id, second.id)
    assert not has_connected_chat(db_session, user.max_user_id)

    second_user = authorize_user(db_session, MaxUserPayload(max_user_id=8))
    add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    add_user_to_chat(db_session, chat.chat_id, max_user_id=second_user.max_user_id)
    assert not has_connected_chat(db_session, user.max_user_id)
    assert list_memberships_for_user(db_session, user.max_user_id) == []
    with pytest.raises(ValueError, match="нет среди домов чата"):
        set_member_address(
            db_session, chat.chat_id, max_user_id=user.max_user_id, address_id=foreign.id
        )

    set_member_address(
        db_session, chat.chat_id, max_user_id=user.max_user_id, address_id=address.id
    )
    set_member_address(
        db_session, chat.chat_id, max_user_id=second_user.max_user_id, address_id=second.id
    )
    assert list_memberships_for_user(db_session, user.max_user_id)[0].address_id == address.id
    assert list_memberships_for_user(db_session, second_user.max_user_id)[0].address_id == second.id
    assert has_connected_chat(db_session, second_user.max_user_id)

    set_member_address(db_session, chat.chat_id, max_user_id=user.max_user_id, address_id=second.id)
    assert list_memberships_for_user(db_session, user.max_user_id)[0].address_id == second.id
    assert list_memberships_for_user(db_session, second_user.max_user_id)[0].address_id == second.id
