"""Заполнить addresses.district по OSM admin_level=8 границам Москвы."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sqlalchemy as sa

from address.district_boundaries import load_overpass_boundaries, resolve_district
from project.database import session_scope


def backfill(path: Path) -> dict[str, int]:
    boundaries = load_overpass_boundaries(path)
    with session_scope() as session:
        rows = session.execute(
            sa.text("SELECT id, latitude, longitude, district FROM addresses")
        ).mappings()
        updates: list[dict[str, object]] = []
        matched = 0
        changed = 0
        for row in rows:
            district = resolve_district(
                boundaries,
                float(row["latitude"]),
                float(row["longitude"]),
            )
            if district is None:
                continue
            matched += 1
            if row["district"] == district:
                continue
            updates.append({"id": row["id"], "district": district})
            changed += 1
            if len(updates) >= 2000:
                session.execute(
                    sa.text("UPDATE addresses SET district=:district WHERE id=:id"), updates
                )
                updates.clear()
        if updates:
            session.execute(
                sa.text("UPDATE addresses SET district=:district WHERE id=:id"), updates
            )
    return {
        "boundaries": len(boundaries),
        "matched_addresses": matched,
        "changed_addresses": changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Overpass JSON с границами admin_level=8")
    args = parser.parse_args()
    try:
        result = backfill(args.source)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Ошибка: {exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
