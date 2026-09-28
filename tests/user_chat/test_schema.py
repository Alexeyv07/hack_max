"""Ограничения БД, направления каскадов и наличие SQL-миграций."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError

from address.db import AddressRow
from auth.db import UserRow
from project.sql_migrate import MIGRATIONS_DIR, available_versions, down_path, up_path
from user_chat.db import ChatRow, users_chat
from user_chat.handlers import add_user_to_chat, list_chat_members


def test_database_rejects_duplicate_chat_id(db_session, chat, address) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            insert(ChatRow).values(chat_id=chat.chat_id, title="Дубль", address_id=address.id)
        )


def test_database_rejects_duplicate_membership(db_session, chat, user) -> None:
    add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(insert(users_chat).values(chat_id=chat.chat_id, user_id=user.id))


def test_database_rejects_missing_address(db_session) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(insert(ChatRow).values(chat_id=42, title="Чат", address_id=999))


@pytest.mark.parametrize("missing", ["user", "chat"])
def test_database_rejects_membership_without_parent(db_session, chat, user, missing) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            insert(users_chat).values(
                chat_id=999 if missing == "chat" else chat.chat_id,
                user_id=999 if missing == "user" else user.id,
            )
        )


def test_address_cannot_be_deleted_while_chat_references_it(db_session, chat, address) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(delete(AddressRow).where(AddressRow.id == address.id))
    assert db_session.get(ChatRow, chat.chat_id) is not None


@pytest.mark.parametrize("loaded", [False, True])
def test_chat_deletion_only_removes_memberships(db_session, chat, address, user, loaded) -> None:
    add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    row = db_session.get(ChatRow, chat.chat_id)
    if loaded:
        assert len(row.users) == 1
    db_session.delete(row)
    db_session.flush()
    assert db_session.scalar(select(users_chat.c.user_id)) is None
    assert db_session.get(UserRow, user.id) is not None
    assert db_session.get(AddressRow, address.id) is not None


def test_user_deletion_keeps_chat_and_address(db_session, chat, address, user) -> None:
    add_user_to_chat(db_session, chat.chat_id, max_user_id=user.max_user_id)
    db_session.execute(delete(UserRow).where(UserRow.id == user.id))
    assert list_chat_members(db_session, chat.chat_id) == []
    assert db_session.get(ChatRow, chat.chat_id) is not None
    assert db_session.get(AddressRow, address.id) is not None


def test_sql_migrations_chain_complete() -> None:
    versions = available_versions()
    assert versions[0] == "0001_create_users"
    assert "0009_create_chats" in versions
    assert "0011_chat_link" in versions
    assert "0014_events_title_nullable" in versions
    assert "0015_api_query_indexes" in versions
    assert "0016_notify_workers" in versions
    assert "0021_chat_addresses" in versions
    assert "0022_user_residence" in versions
    assert "0023_group_welcome_message" in versions
    assert "0024_notify_delivery_message_mid" in versions
    assert "0025_bot_group_registry" in versions
    assert versions[-1] == "0027_user_chat_address_order"
    for version in versions:
        assert up_path(version).is_file()
        assert down_path(version).is_file()
    assert MIGRATIONS_DIR.is_dir()
    # нет «осиротевших» файлов
    names = {p.name for p in MIGRATIONS_DIR.glob("*.sql")}
    expected = {f"{v}.up.sql" for v in versions} | {f"{v}.down.sql" for v in versions}
    assert names == expected
