"""Ограничения БД, направления каскадов и новая миграция."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import delete, insert, inspect, select
from sqlalchemy.exc import IntegrityError

from address.db import AddressRow
from auth.db import UserRow
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


def test_new_migration_reversible_and_does_not_infer_membership(engine) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == "0015_notify_digest_cursor"
    notify_revision = scripts.get_revision("0015_notify_digest_cursor")
    assert notify_revision.down_revision == "0014_notify_workers"
    notify_base = scripts.get_revision("0014_notify_workers")
    assert notify_base.down_revision == "0013_events_active_window"
    active_window = scripts.get_revision("0013_events_active_window")
    assert active_window.down_revision == "0012_chat_group_type"
    group_type_revision = scripts.get_revision("0012_chat_group_type")
    assert group_type_revision.down_revision == "0011_chat_link"
    chat_link_revision = scripts.get_revision("0011_chat_link")
    assert chat_link_revision.down_revision == "0010_mc_parser"
    mc_revision = scripts.get_revision("0010_mc_parser")
    assert mc_revision.down_revision == "0009_create_chats"

    revision = scripts.get_revision("0009_create_chats")
    assert revision.down_revision == "0008_events_published_at"
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        revision.module.downgrade()
        connection.execute(insert(UserRow).values(max_user_id=7, chat_id=42))
        revision.module.upgrade()
        assert connection.execute(select(users_chat)).all() == []
        assert connection.execute(select(ChatRow.chat_id)).all() == []
        assert connection.execute(select(UserRow.max_user_id)).scalar_one() == 7
        assert inspect(connection).get_pk_constraint("users_chat")["constrained_columns"] == [
            "user_id",
            "chat_id",
        ]
        revision.module.downgrade()
        assert "users_chat" not in inspect(connection).get_table_names()
        assert "chats" not in inspect(connection).get_table_names()
        assert connection.execute(select(UserRow.max_user_id)).scalar_one() == 7
