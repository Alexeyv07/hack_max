"""Общая логика SQL-миграций (для scripts/migrate.py и тестов)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "db" / "migrations"
_VERSION_RE = re.compile(r"^(\d{4}_[a-z0-9_]+)\.(up|down)\.sql$")


def available_versions() -> list[str]:
    versions: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.up.sql")):
        match = _VERSION_RE.match(path.name)
        if match:
            versions.append(match.group(1))
    return versions


def up_path(version: str) -> Path:
    return MIGRATIONS_DIR / f"{version}.up.sql"


def down_path(version: str) -> Path:
    return MIGRATIONS_DIR / f"{version}.down.sql"


def apply_sql(connection, sql: str) -> None:
    """Выполнить SQL-файл (несколько statements) через SQLAlchemy connection."""
    connection.exec_driver_sql(sql)


def upgrade_all(connection) -> list[str]:
    applied: list[str] = []
    for version in available_versions():
        apply_sql(connection, up_path(version).read_text(encoding="utf-8"))
        applied.append(version)
    return applied


def downgrade_all(connection, versions: list[str] | None = None) -> None:
    order = list(reversed(versions if versions is not None else available_versions()))
    for version in order:
        path = down_path(version)
        if path.is_file():
            apply_sql(connection, path.read_text(encoding="utf-8"))
