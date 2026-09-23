"""SQL-миграции (замена Alembic): up / down / status / stamp.

Файлы: db/migrations/NNNN_name.up.sql + .down.sql
Таблица учёта: schema_migrations(version).

  PYTHONPATH=src python scripts/migrate.py status
  PYTHONPATH=src python scripts/migrate.py up
  PYTHONPATH=src python scripts/migrate.py down
  PYTHONPATH=src python scripts/migrate.py down --steps 3
  PYTHONPATH=src python scripts/migrate.py stamp
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2
from psycopg2.extensions import connection as PgConnection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from project.sql_migrate import (  # noqa: E402
    MIGRATIONS_DIR,
    available_versions,
    down_path,
    up_path,
)


def _connect() -> PgConnection:
    from project.config import get_settings

    db = get_settings().database
    return psycopg2.connect(
        host=db.host,
        port=db.port,
        dbname=db.name,
        user=db.user,
        password=db.password,
    )


def _ensure_bookkeeping(conn: PgConnection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'alembic_version'
            )
            """
        )
        has_alembic = bool(cur.fetchone()[0])
        if not has_alembic:
            return
        cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
        row = cur.fetchone()
        if row is None:
            return
        cur.execute("SELECT COUNT(*) FROM schema_migrations")
        if int(cur.fetchone()[0]) > 0:
            return
        versions = available_versions()
        if versions and row[0] in (versions[-1], "0013_events_active_window"):
            for version in versions:
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
                    (version,),
                )
            print(f"migrate: stamped from alembic_version={row[0]}", flush=True)


def applied_versions(conn: PgConnection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        return [row[0] for row in cur.fetchall()]


def _run_sql_file(conn: PgConnection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def cmd_status(conn: PgConnection) -> int:
    applied = set(applied_versions(conn))
    versions = available_versions()
    pending = [v for v in versions if v not in applied]
    print(f"applied: {len(applied)} / {len(versions)}")
    if applied:
        print(f"current: {sorted(applied)[-1]}")
    if pending:
        print("pending:")
        for version in pending:
            print(f"  - {version}")
    else:
        print("pending: (none)")
    return 0


def cmd_up(conn: PgConnection) -> int:
    applied = set(applied_versions(conn))
    for version in available_versions():
        if version in applied:
            continue
        print(f"UP {version}", flush=True)
        _run_sql_file(conn, up_path(version))
        with conn.cursor() as cur:
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        conn.commit()
    print("migrate up: done", flush=True)
    return 0


def cmd_down(conn: PgConnection, *, steps: int) -> int:
    applied = applied_versions(conn)
    if not applied:
        print("migrate down: nothing to revert", flush=True)
        return 0
    for version in list(reversed(applied))[:steps]:
        path = down_path(version)
        if not path.is_file():
            raise FileNotFoundError(f"нет down-файла: {path}")
        print(f"DOWN {version}", flush=True)
        _run_sql_file(conn, path)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM schema_migrations WHERE version = %s", (version,))
        conn.commit()
    print("migrate down: done", flush=True)
    return 0


def cmd_stamp(conn: PgConnection) -> int:
    with conn.cursor() as cur:
        for version in available_versions():
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
                (version,),
            )
    conn.commit()
    print("migrate stamp: all versions marked applied", flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("up")
    down_p = sub.add_parser("down")
    down_p.add_argument("--steps", type=int, default=1)
    sub.add_parser("stamp")
    args = parser.parse_args()

    if not MIGRATIONS_DIR.is_dir():
        parser.exit(1, f"нет каталога миграций: {MIGRATIONS_DIR}\n")

    conn = _connect()
    try:
        conn.autocommit = False
        _ensure_bookkeeping(conn)
        conn.commit()
        if args.cmd == "status":
            code = cmd_status(conn)
        elif args.cmd == "up":
            code = cmd_up(conn)
        elif args.cmd == "down":
            code = cmd_down(conn, steps=max(1, args.steps))
        elif args.cmd == "stamp":
            code = cmd_stamp(conn)
        else:
            parser.exit(2, f"unknown cmd {args.cmd}\n")
        raise SystemExit(code)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
