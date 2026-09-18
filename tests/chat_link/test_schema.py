"""Схема ChatLinks и миграция KAN-7."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect


def test_chat_links_migration_is_head_and_reversible(engine) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("0010_create_chat_links")
    assert scripts.get_current_head() == revision.revision
    assert revision.down_revision == "0009_create_chats"

    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        revision.module.downgrade()
        assert "chat_links" not in inspect(connection).get_table_names()
        revision.module.upgrade()
        inspector = inspect(connection)
        assert "chat_links" in inspector.get_table_names()
        assert inspector.get_pk_constraint("chat_links")["constrained_columns"] == ["token"]
