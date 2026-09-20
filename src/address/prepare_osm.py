"""Подготовить московский справочник из локального Overpass JSON, без сети и БД."""

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from address.district_boundaries import load_overpass_boundaries, resolve_district
from address.gar_postcodes import build_index, lookup, street_key
from address.seed import read_addresses


def convert_element(element):
    tags = element["tags"]
    coordinates = element.get("center", element)
    parts = ["Москва"]
    # Не меняем старый natural key address_text: до KAN-7 в него попадали
    # addr:city/suburb/place. addr:district сохраняем отдельным компонентом.
    text_locality: list[str] = []
    for field in ("addr:city", "addr:suburb", "addr:place"):
        value = tags.get(field, "").strip()
        if (
            value
            and value.casefold() != "москва"
            and value.casefold() not in {part.casefold() for part in parts + text_locality}
        ):
            text_locality.append(value)
    parts.extend(text_locality)

    district = None
    for field in ("addr:district", "addr:suburb", "addr:place", "addr:city"):
        value = tags.get(field, "").strip()
        if value and value.casefold() != "москва":
            district = value
            break
    street, house = tags["addr:street"].strip(), tags["addr:housenumber"].strip()
    if not street or not house:
        raise ValueError("Объект без улицы или номера дома")
    parts.extend([street, "д. " + house])
    postcode = tags.get("addr:postcode", "").strip()
    building = tags.get("building")
    private = True if building in {"house", "detached", "semidetached_house"} else None
    if building == "apartments":
        private = False
    return {
        "address_text": ", ".join(parts),
        "city": "Москва",
        "district": district,
        "street": street,
        "house": house,
        "postal_code": postcode if re.fullmatch(r"[0-9]{6}", postcode) else None,
        "latitude": coordinates["lat"],
        "longitude": coordinates["lon"],
        "is_private": private,
        "source_key": f"osm:{element['type']}/{element['id']}",
        "osm_street": street,
        "osm_house": house,
    }


def deduplicate(rows):
    """Конфликтующие PK исключаем целиком: не угадываем дом по одинаковой строке."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["address_text"]].append(row)
    accepted, rejected = [], []
    fields = ("latitude", "longitude", "postal_code", "is_private")
    for address, group in sorted(groups.items()):
        values = {tuple(row[field] for field in fields) for row in group}
        if len(values) > 1:
            rejected.append(
                {"address_text": address, "reason": "conflicting_primary_key", "rows": group}
            )
        else:
            chosen = dict(min(group, key=lambda row: row["source_key"]))
            chosen["source_keys"] = sorted(row["source_key"] for row in group)
            accepted.append(chosen)
    return accepted, rejected


def prepare(source, output, *, gar_index=None, district_boundaries=None):
    raw_bytes = source.read_bytes()
    raw = json.loads(raw_bytes)
    if raw.get("remark") or not raw.get("elements"):
        raise ValueError("Overpass вернул ошибку или пустую выгрузку")
    rows = [convert_element(element) for element in raw["elements"]]
    if len({row["source_key"] for row in rows}) != len(rows):
        raise ValueError("Повторяются идентификаторы OSM")
    rows, rejected = deduplicate(rows)

    boundaries = []
    districts_resolved = 0
    if district_boundaries:
        boundaries = load_overpass_boundaries(district_boundaries)
        for row in rows:
            district = resolve_district(boundaries, row["latitude"], row["longitude"])
            if district:
                row["district"] = district
                districts_resolved += 1

    before = sum(row["postal_code"] is not None for row in rows)
    sdk_version, filled = None, 0
    if gar_index:
        index, sdk_version = build_index(
            gar_index,
            wanted_streets={
                street_key(row["osm_street"]) for row in rows if row["postal_code"] is None
            },
        )
        for row in rows:
            if row["postal_code"] is not None:
                continue
            match = lookup(
                index, row["osm_street"], row["osm_house"], row["latitude"], row["longitude"]
            )
            if match:
                row.update(match)
                row["postcode_source"] = "garfias.ru/Pullenti"
                filled += 1
    for row in rows:
        if row["postal_code"] and "postcode_source" not in row:
            row["postcode_source"] = "OpenStreetMap"
        row.pop("osm_street")
        row.pop("osm_house")
    output.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()
    target = output / "moscow.jsonl.gz"
    temporary = output / ".moscow.jsonl.gz"
    temporary.write_bytes(gzip.compress(payload, mtime=0))
    read_addresses(temporary)  # та же проверка, что перед импортом в БД
    temporary.replace(target)
    (output / "rejected.jsonl.gz").write_bytes(
        gzip.compress(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rejected).encode(),
            mtime=0,
        )
    )
    manifest = {
        "osm_source": "https://www.openstreetmap.org/copyright",
        "osm_license": "ODbL-1.0",
        "osm_metadata": raw.get("osm3s", {}),
        "scope": "RU-MOW: buildings with addr:street and addr:housenumber",
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "gzip_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "input_rows": len(raw["elements"]),
        "rows": len(rows),
        "rejected_address_groups": len(rejected),
        "rejected_rows": sum(len(item["rows"]) for item in rejected),
        "with_osm_postcode": before,
        "filled_from_gar": filled,
        "without_postcode": len(rows) - before - filled,
        "gar_sdk_version": sdk_version,
        "gar_source": "https://garfias.ru" if gar_index else None,
        "gar_index_version": (gar_index / "version.txt").read_text().strip() if gar_index else None,
        "district_boundaries": len(boundaries),
        "districts_resolved": districts_resolved,
        "private_counts": dict(Counter(str(row["is_private"]) for row in rows)),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="Каталог результата")
    parser.add_argument("--gar-index", type=Path, help="Необязательно: локальный Gar77")
    parser.add_argument(
        "--district-boundaries",
        type=Path,
        help="Необязательно: Overpass JSON границ Москвы admin_level=8",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                args.source,
                args.output,
                gar_index=args.gar_index,
                district_boundaries=args.district_boundaries,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
