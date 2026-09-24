"""Собрать CSV-дампы для Postgres init (`COPY`), без Python-seed в runtime.

Из jsonl.gz → docker/postgres/seed/*.csv.gz

  PYTHONPATH=src python scripts/build_pg_seed_dumps.py
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from address.seed import DEFAULT_ADDRESSES_FILE, read_addresses  # noqa: E402

DEFAULT_EVENTS = ROOT / "src" / "parser_common" / "data" / "bootstrap_events.jsonl.gz"
DEFAULT_OUT = ROOT / "docker" / "postgres" / "seed"

ADDRESS_COLS = (
    "id",
    "postal_code",
    "address_text",
    "city",
    "district",
    "street",
    "house",
    "latitude",
    "longitude",
    "is_private",
)

EVENT_COLS = (
    "id",
    "title",
    "body",
    "importance",
    "source",
    "address_id",
    "geo_by",
    "weight",
    "source_msg_id",
    "disaster_flag",
    "source_url",
    "image_url",
    "published_at",
    "active_from",
    "active_to",
    "created_at",
    "updated_at",
)


def _csv_cell(value: object) -> str:
    if value is None:
        return r"\N"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _parse_dt(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def write_addresses_csv(path: Path, addresses_file: Path) -> dict[str, int]:
    rows = read_addresses(addresses_file)
    text_to_id: dict[str, int] = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(ADDRESS_COLS)
        for idx, row in enumerate(rows, start=1):
            text_to_id[row["address_text"]] = idx
            writer.writerow(
                [
                    _csv_cell(idx),
                    _csv_cell(row.get("postal_code")),
                    _csv_cell(row["address_text"]),
                    _csv_cell(row.get("city")),
                    _csv_cell(row.get("district")),
                    _csv_cell(row.get("street")),
                    _csv_cell(row.get("house")),
                    _csv_cell(row["latitude"]),
                    _csv_cell(row["longitude"]),
                    _csv_cell(row.get("is_private")),
                ]
            )
    return text_to_id


def write_events_csv(
    path: Path,
    events_file: Path,
    text_to_id: dict[str, int],
) -> int:
    if not events_file.is_file():
        print(f"WARN: no events snapshot ({events_file}) — empty events.csv.gz", file=sys.stderr)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8", newline="") as out:
            csv.writer(out, lineterminator="\n").writerow(EVENT_COLS)
        return 0

    opener = gzip.open if events_file.suffix == ".gz" else open
    items: list[dict] = []
    with opener(events_file, "rt", encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                items.append(item)

    now = datetime.now(UTC).isoformat()
    seen: set[tuple[str, str]] = set()
    written = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(EVENT_COLS)
        for item in items:
            msg_id = item.get("source_msg_id")
            if not isinstance(msg_id, str) or not msg_id.strip():
                continue
            source = str(item.get("source") or "news")
            key = (source, msg_id)
            if key in seen:
                continue
            title = item.get("title")
            body = item.get("body")
            if not isinstance(title, str) or not isinstance(body, str):
                continue
            address_id = None
            text = item.get("address_text")
            if isinstance(text, str) and text.strip():
                address_id = text_to_id.get(text.strip())
            weight = item.get("weight")
            try:
                weight_f = float(weight) if weight is not None else 0.0
            except (TypeError, ValueError):
                weight_f = 0.0
            seen.add(key)
            written += 1
            writer.writerow(
                [
                    _csv_cell(written),
                    _csv_cell(title),
                    _csv_cell(body),
                    _csv_cell(int(item.get("importance", 3))),
                    _csv_cell(source),
                    _csv_cell(address_id),
                    _csv_cell(item.get("geo_by") if isinstance(item.get("geo_by"), str) else None),
                    _csv_cell(weight_f),
                    _csv_cell(msg_id),
                    _csv_cell(bool(item.get("disaster_flag", False))),
                    _csv_cell(
                        item.get("source_url") if isinstance(item.get("source_url"), str) else None
                    ),
                    _csv_cell(
                        item.get("image_url") if isinstance(item.get("image_url"), str) else None
                    ),
                    _csv_cell(_parse_dt(item.get("published_at"))),
                    _csv_cell(_parse_dt(item.get("active_from"))),
                    _csv_cell(_parse_dt(item.get("active_to"))),
                    _csv_cell(now),
                    _csv_cell(now),
                ]
            )
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addresses", type=Path, default=DEFAULT_ADDRESSES_FILE)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    addr_csv = args.out / "addresses.csv.gz"
    events_csv = args.out / "events.csv.gz"
    print(f"addresses <- {args.addresses}")
    text_to_id = write_addresses_csv(addr_csv, args.addresses)
    print(f"  -> {addr_csv} ({len(text_to_id)} rows)")
    n_events = write_events_csv(events_csv, args.events, text_to_id)
    print(f"events <- {args.events}")
    print(f"  -> {events_csv} ({n_events} rows)")


if __name__ == "__main__":
    main()
