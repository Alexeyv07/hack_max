"""Дамп / загрузка runtime-данных Postgres (для демо судьям).

addresses и events сюда НЕ входят — они из отдельного seed:
  docker/postgres/seed/addresses.csv.gz
  docker/postgres/seed/events.csv.gz
  (собрать: PYTHONPATH=src python scripts/build_pg_seed_dumps.py)

По умолчанию дамп -> docker/postgres/seed/runtime/*.csv.gz (+ manifest.json).

  PYTHONPATH=src python scripts/dump_db.py dump
  PYTHONPATH=src python scripts/dump_db.py load
  PYTHONPATH=src python scripts/dump_db.py dump --include-addresses --include-events
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
from pathlib import Path

import psycopg2
from psycopg2.extensions import connection as PgConnection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_OUT = ROOT / "docker" / "postgres" / "seed" / "runtime"

# Порядок загрузки с учётом FK (addresses/events уже в БД из seed).
LOAD_ORDER: tuple[str, ...] = (
    "users",
    "chats",
    "users_chat",
    "chat_addresses",
    "chat_links",
    "bot_group_registry",
    "news_parser_cursors",
    "mc_parser_cursors",
    "notify_cursors",
    "notify_digests",
    "notify_chat_messages",
    "notify_deliveries",
)

ALWAYS_EXCLUDE: frozenset[str] = frozenset(
    {
        "schema_migrations",
        "alembic_version",
    }
)

DEFAULT_EXCLUDE: frozenset[str] = frozenset({"addresses", "events"}) | ALWAYS_EXCLUDE


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


def _list_public_tables(conn: PgConnection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
        return [str(row[0]) for row in cur.fetchall()]


def _table_columns(conn: PgConnection, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [str(row[0]) for row in cur.fetchall()]


def _row_count(conn: PgConnection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        return int(cur.fetchone()[0])


def _tables_for_dump(
    conn: PgConnection,
    *,
    include_addresses: bool,
    include_events: bool,
) -> list[str]:
    exclude = set(ALWAYS_EXCLUDE)
    if not include_addresses:
        exclude.add("addresses")
    if not include_events:
        exclude.add("events")

    existing = set(_list_public_tables(conn))
    ordered: list[str] = []
    for name in LOAD_ORDER:
        if name in existing and name not in exclude:
            ordered.append(name)
    for name in sorted(existing):
        if name not in exclude and name not in ordered:
            ordered.append(name)
    return ordered


def _dump_table(conn: PgConnection, table: str, path: Path) -> int:
    columns = _table_columns(conn, table)
    if not columns:
        raise RuntimeError(f"таблица {table}: нет колонок")
    cols_sql = ", ".join(f'"{c}"' for c in columns)
    buf = io.StringIO()
    with conn.cursor() as cur:
        cur.copy_expert(
            f"COPY \"{table}\" ({cols_sql}) TO STDOUT WITH (FORMAT csv, HEADER true, NULL '\\N')",
            buf,
        )
    raw = buf.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as out:
        out.write(raw)
    # строк данных = строк файла минус header (если файл не пустой)
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    return max(0, len(lines) - 1) if lines else 0


def cmd_dump(args: argparse.Namespace) -> int:
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = _connect()
    try:
        tables = _tables_for_dump(
            conn,
            include_addresses=args.include_addresses,
            include_events=args.include_events,
        )
        manifest: dict[str, object] = {
            "format": "hack_max_runtime_seed_v1",
            "exclude_default": sorted(DEFAULT_EXCLUDE),
            "include_addresses": bool(args.include_addresses),
            "include_events": bool(args.include_events),
            "tables": [],
        }
        entries: list[dict[str, object]] = []
        for table in tables:
            gz = out_dir / f"{table}.csv.gz"
            n = _dump_table(conn, table, gz)
            cols = _table_columns(conn, table)
            entries.append(
                {
                    "table": table,
                    "file": gz.name,
                    "rows": n,
                    "columns": cols,
                }
            )
            print(f"  {table}: {n} rows -> {gz.name}")
        manifest["tables"] = entries
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"manifest -> {manifest_path}")
        print(f"dump: ok ({len(entries)} tables)")
    finally:
        conn.close()
    return 0


def _read_csv_header(gz_path: Path) -> list[str]:
    with gzip.open(gz_path, "rt", encoding="utf-8", newline="") as src:
        reader = csv.reader(src)
        header = next(reader, None)
    if not header:
        raise RuntimeError(f"{gz_path.name}: пустой CSV")
    return header


def _load_table(conn: PgConnection, table: str, gz_path: Path, columns: list[str]) -> int:
    cols_sql = ", ".join(f'"{c}"' for c in columns)
    with gzip.open(gz_path, "rt", encoding="utf-8", newline="") as src:
        # пропускаем header — COPY HEADER true сам прочитает
        data = src.read()
    buf = io.StringIO(data)
    with conn.cursor() as cur:
        cur.copy_expert(
            f"COPY \"{table}\" ({cols_sql}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\\N')",
            buf,
        )
        # serial sequences
        cur.execute(
            """
            SELECT pg_get_serial_sequence(%s, 'id')
            """,
            (table,),
        )
        seq_row = cur.fetchone()
        if seq_row and seq_row[0]:
            cur.execute(
                f'SELECT setval(%s, COALESCE((SELECT MAX(id) FROM "{table}"), 1))',
                (seq_row[0],),
            )
    lines = [ln for ln in data.splitlines() if ln.strip()]
    return max(0, len(lines) - 1) if lines else 0


def _resolve_load_plan(out_dir: Path, conn: PgConnection) -> list[tuple[str, Path, list[str]]]:
    manifest_path = out_dir / "manifest.json"
    existing = set(_list_public_tables(conn))
    plan: list[tuple[str, Path, list[str]]] = []

    if manifest_path.is_file():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in data.get("tables") or []:
            table = str(entry["table"])
            if table in ALWAYS_EXCLUDE or table not in existing:
                continue
            gz = out_dir / str(entry.get("file") or f"{table}.csv.gz")
            if not gz.is_file():
                print(f"WARN: нет файла {gz.name} — skip {table}", file=sys.stderr)
                continue
            cols = list(entry.get("columns") or [])
            if not cols:
                cols = _read_csv_header(gz)
            plan.append((table, gz, cols))
        return plan

    # без manifest: LOAD_ORDER + остальные *.csv.gz
    seen: set[str] = set()
    for table in LOAD_ORDER:
        gz = out_dir / f"{table}.csv.gz"
        if table in existing and table not in ALWAYS_EXCLUDE and gz.is_file():
            plan.append((table, gz, _read_csv_header(gz)))
            seen.add(table)
    for gz in sorted(out_dir.glob("*.csv.gz")):
        table = gz.name[: -len(".csv.gz")]
        if table in seen or table in ALWAYS_EXCLUDE or table not in existing:
            continue
        if table in DEFAULT_EXCLUDE:
            # addresses/events грузятся другим скриптом
            continue
        plan.append((table, gz, _read_csv_header(gz)))
    return plan


def cmd_load(args: argparse.Namespace) -> int:
    out_dir: Path = args.from_dir
    if not out_dir.is_dir():
        print(f"ERROR: нет каталога {out_dir}", file=sys.stderr)
        return 1

    conn = _connect()
    conn.autocommit = False
    try:
        plan = _resolve_load_plan(out_dir, conn)
        if not plan:
            print(f"WARN: в {out_dir} нет runtime csv.gz — нечего грузить")
            return 0

        for table, gz, columns in plan:
            n_existing = _row_count(conn, table)
            if n_existing > 0 and not args.force:
                print(f"  {table}: уже {n_existing} rows — skip (нужен --force)")
                continue
            if n_existing > 0 and args.force:
                with conn.cursor() as cur:
                    cur.execute(f'TRUNCATE TABLE "{table}" CASCADE')
                print(f"  {table}: TRUNCATE CASCADE")
            # колонки, которые есть и в дампе, и в текущей схеме
            live_cols = set(_table_columns(conn, table))
            use_cols = [c for c in columns if c in live_cols]
            missing = [c for c in columns if c not in live_cols]
            if missing:
                print(
                    f"WARN: {table}: колонки из дампа отсутствуют в схеме, drop: {missing}",
                    file=sys.stderr,
                )
            if not use_cols:
                print(f"ERROR: {table}: нет общих колонок", file=sys.stderr)
                conn.rollback()
                return 1
            # если набор колонок сузили — переписать CSV без лишних полей
            if use_cols != columns:
                n = _load_table_filtered(conn, table, gz, columns, use_cols)
            else:
                n = _load_table(conn, table, gz, use_cols)
            print(f"  {table}: loaded {n} rows from {gz.name}")
        conn.commit()
        print("load: ok")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


def _load_table_filtered(
    conn: PgConnection,
    table: str,
    gz_path: Path,
    file_columns: list[str],
    use_columns: list[str],
) -> int:
    """COPY с подмножеством колонок (схема новее/старее дампа)."""
    idx = [file_columns.index(c) for c in use_columns]
    out_buf = io.StringIO()
    writer = csv.writer(out_buf, lineterminator="\n")
    writer.writerow(use_columns)
    rows = 0
    with gzip.open(gz_path, "rt", encoding="utf-8", newline="") as src:
        reader = csv.reader(src)
        header = next(reader, None)
        if header is None:
            return 0
        for row in reader:
            if not row:
                continue
            writer.writerow([row[i] if i < len(row) else r"\N" for i in idx])
            rows += 1
    out_buf.seek(0)
    cols_sql = ", ".join(f'"{c}"' for c in use_columns)
    with conn.cursor() as cur:
        cur.copy_expert(
            f"COPY \"{table}\" ({cols_sql}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\\N')",
            out_buf,
        )
        cur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
        seq_row = cur.fetchone()
        if seq_row and seq_row[0]:
            cur.execute(
                f'SELECT setval(%s, COALESCE((SELECT MAX(id) FROM "{table}"), 1))',
                (seq_row[0],),
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump", help="выгрузить runtime-таблицы в csv.gz")
    p_dump.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p_dump.add_argument(
        "--include-addresses",
        action="store_true",
        help="включить addresses (обычно не нужно — есть seed)",
    )
    p_dump.add_argument(
        "--include-events",
        action="store_true",
        help="включить events (обычно не нужно — есть seed)",
    )
    p_dump.set_defaults(func=cmd_dump)

    p_load = sub.add_parser("load", help="загрузить runtime csv.gz в живую БД")
    p_load.add_argument("--from", dest="from_dir", type=Path, default=DEFAULT_OUT)
    p_load.add_argument(
        "--force",
        action="store_true",
        help="TRUNCATE CASCADE таблицу перед COPY, если уже есть строки",
    )
    p_load.set_defaults(func=cmd_load)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
