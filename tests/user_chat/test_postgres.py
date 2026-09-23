"""Проверка handlers на настоящей мигрированной PostgreSQL; отдельная схема, rollback."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from address.db import AddressRow
from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload
from user_chat.db import ChatRow
from user_chat.handlers import (
    add_user_to_chat,
    create_chat,
    list_chat_members,
    list_memberships_for_user,
    set_member_address,
)
from user_chat.models import ChatCreate


@pytest.mark.skipif(
    not os.getenv("ADDRESS_TEST_DATABASE_URL"), reason="Нужен ADDRESS_TEST_DATABASE_URL"
)
def test_postgres_membership_and_delete_constraints() -> None:
    engine = create_engine(os.environ["ADDRESS_TEST_DATABASE_URL"])
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                schema = "chat_test_" + uuid.uuid4().hex
                connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
                connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
                with Operations.context(MigrationContext.configure(connection)):
                    for revision in reversed(list(scripts.walk_revisions())):
                        revision.module.upgrade()
                with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                    address = AddressRow(address_text="Тест PostgreSQL", latitude=55, longitude=37)
                    session.add(address)
                    session.flush()
                    user = authorize_user(session, MaxUserPayload(max_user_id=2**40))
                    chat = create_chat(session, ChatCreate(chat_id=-(2**40), address_id=address.id))
                    assert add_user_to_chat(session, chat.chat_id, max_user_id=user.max_user_id)
                    assert not add_user_to_chat(session, chat.chat_id, max_user_id=user.max_user_id)
                    set_member_address(
                        session, chat.chat_id, max_user_id=user.max_user_id, address_id=address.id
                    )
                    assert len(list_chat_members(session, chat.chat_id)) == 1
                    assert list_memberships_for_user(session, user.max_user_id)[0].lat == 55
                    with pytest.raises(IntegrityError), session.begin_nested():
                        session.execute(delete(AddressRow).where(AddressRow.id == address.id))
                    session.execute(delete(ChatRow).where(ChatRow.chat_id == chat.chat_id))
                    assert list_chat_members(session, chat.chat_id) == []
                    assert session.get(AddressRow, address.id) is not None
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
