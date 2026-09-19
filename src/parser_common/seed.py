"""Снимок bootstrap-событий (все sources): dump / seed в БД."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from address.db.address import AddressRow
from address.resolve import get_or_create_city_address
from events.db.event import EventRow
from events.handlers.crud import create_event, list_existing_source_msg_ids
from events.models.event import EventCreate
from project.database import session_scope
from project.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_SNAPSHOT = Path(__file__).resolve().parent / "data" / "bootstrap_events.jsonl.gz"


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def dump_events_snapshot(session: Session, path: Path, *, limit: int = 2000) -> int:
    """Сохранить последние события **всех** sources в JSONL.GZ."""
    rows = list(
        session.scalars(
            select(EventRow)
            .options(joinedload(EventRow.address))
            .order_by(EventRow.id.desc())
            .limit(limit)
        ).unique()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for row in reversed(rows):
        address = row.address
        payload = {
            "title": row.title,
            "body": row.body,
            "importance": row.importance,
            "source": row.source,
            "source_msg_id": row.source_msg_id,
            "disaster_flag": row.disaster_flag,
            "source_url": row.source_url,
            "image_url": row.image_url,
            "geo_by": row.geo_by,
            "weight": row.weight,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "address_text": address.address_text if address else None,
            "address_city": address.city if address else None,
            "address_street": address.street if address else None,
            "address_house": address.house if address else None,
        }
        lines.append(json.dumps(payload, ensure_ascii=False))

    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as out:
        out.write("\n".join(lines) + ("\n" if lines else ""))
    logger.info("Snapshot событий (все sources): %d → %s", len(lines), path)
    return len(lines)


def _resolve_address_id(session: Session, item: dict) -> int | None:
    text = item.get("address_text")
    if isinstance(text, str) and text.strip():
        row = session.scalar(select(AddressRow).where(AddressRow.address_text == text.strip()))
        if row is not None and row.id is not None:
            return row.id
    city = item.get("address_city")
    if isinstance(city, str) and city.strip() and not item.get("address_street"):
        return get_or_create_city_address(session, city.strip()).id
    return None


def load_events_snapshot(session: Session, path: Path) -> int:
    """Идемпотентная загрузка snapshot по (source, source_msg_id)."""
    if not path.is_file():
        raise FileNotFoundError(f"Нет файла snapshot: {path}")

    opener = gzip.open if path.suffix == ".gz" else open
    items: list[dict] = []
    with opener(path, "rt", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"Строка {line_number}: нужен JSON-объект")
            items.append(item)

    by_source: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        src = str(item.get("source") or "news")
        by_source[src].append(item)

    existing: set[tuple[str, str]] = set()
    for src, group in by_source.items():
        msg_ids = [str(i["source_msg_id"]) for i in group if i.get("source_msg_id")]
        found = list_existing_source_msg_ids(session, source=src, source_msg_ids=msg_ids)
        existing.update((src, mid) for mid in found)

    created = 0
    for item in items:
        msg_id = item.get("source_msg_id")
        if not isinstance(msg_id, str) or not msg_id.strip():
            continue
        source = str(item.get("source") or "news")
        if (source, msg_id) in existing:
            continue
        title = item.get("title")
        body = item.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            continue
        create_event(
            session,
            EventCreate(
                title=title,
                body=body,
                importance=int(item.get("importance", 3)),
                source=source,
                address_id=_resolve_address_id(session, item),
                geo_by=item.get("geo_by") if isinstance(item.get("geo_by"), str) else None,
                source_msg_id=msg_id,
                disaster_flag=bool(item.get("disaster_flag", False)),
                source_url=item.get("source_url")
                if isinstance(item.get("source_url"), str)
                else None,
                image_url=item.get("image_url") if isinstance(item.get("image_url"), str) else None,
                published_at=_parse_dt(item.get("published_at")),
            ),
        )
        existing.add((source, msg_id))
        created += 1
    return created


def ensure_events_seeded(path: Path = DEFAULT_SNAPSHOT) -> bool:
    """Загрузить snapshot, только если таблица events пуста."""
    if not path.is_file():
        logger.info("Snapshot событий отсутствует (%s) — пропуск seed", path)
        return False
    with session_scope() as session:
        has_any = session.scalar(select(EventRow.id).limit(1))
        if has_any is not None:
            return False
        created = load_events_snapshot(session, path)
        logger.info("Загружено событий из snapshot: %d", created)
        return created > 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    dump_p = sub.add_parser("dump", help="Сохранить все events → JSONL.GZ")
    dump_p.add_argument("file", type=Path, nargs="?", default=DEFAULT_SNAPSHOT)
    dump_p.add_argument("--limit", type=int, default=2000)

    load_p = sub.add_parser("load", help="Загрузить JSONL.GZ → events")
    load_p.add_argument("file", type=Path, nargs="?", default=DEFAULT_SNAPSHOT)

    args = parser.parse_args()
    if args.cmd == "dump":
        with session_scope() as session:
            n = dump_events_snapshot(session, args.file, limit=args.limit)
        print(json.dumps({"written": n, "path": str(args.file)}))
    elif args.cmd == "load":
        with session_scope() as session:
            n = load_events_snapshot(session, args.file)
        print(json.dumps({"created": n, "path": str(args.file)}))


if __name__ == "__main__":
    main()
