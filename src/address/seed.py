"""Загрузка локального JSONL/JSONL.gz: python -m address.seed --help."""

import argparse
import gzip
import json
import re
from decimal import Decimal, InvalidOperation
from itertools import batched
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from address.components import parse_address_text
from address.db.address import AddressRow
from project.database import session_scope


def _normalize_optional_str(value: object, *, field: str, max_len: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} должен быть строкой или null")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} длиннее {max_len} символов")
    return text


def read_addresses(path: Path) -> list[dict]:
    """Проверить весь файл до записи; конфликтующие адреса не объединять наугад."""
    addresses = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("нужен JSON-объект")
                text = item.get("address_text")
                if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
                    raise ValueError("нужен address_text длиной 1–1000 символов")
                row = {"address_text": text.strip()}
                for field, limit in (("latitude", 90), ("longitude", 180)):
                    value = Decimal(str(item.get(field)))
                    if not value.is_finite() or not -limit <= value <= limit:
                        raise ValueError(f"некорректный {field}")
                    row[field] = value
                postcode = item.get("postal_code")
                if postcode is not None and (
                    not isinstance(postcode, str) or not re.fullmatch(r"[0-9]{6}", postcode)
                ):
                    raise ValueError("postal_code должен быть строкой из 6 цифр или null")
                private = item.get("is_private")
                if private is not None and type(private) is not bool:
                    raise ValueError("is_private должен быть true, false или null")

                city = _normalize_optional_str(item.get("city"), field="city", max_len=128)
                street = _normalize_optional_str(item.get("street"), field="street", max_len=512)
                house = _normalize_optional_str(item.get("house"), field="house", max_len=64)
                if city is None and street is None and house is None:
                    parsed = parse_address_text(row["address_text"])
                    city, street, house = parsed.city, parsed.street, parsed.house

                row.update(
                    postal_code=postcode,
                    is_private=private,
                    city=city,
                    street=street,
                    house=house,
                )
                key = row["address_text"]
                if key in addresses and addresses[key] != row:
                    raise ValueError(f"разные данные для одного address_text: {key}")
                addresses[key] = row
            except (ValueError, InvalidOperation) as exc:
                raise ValueError(f"Строка {line_number}: {exc}") from exc
    if not addresses:
        raise ValueError("Файл не содержит адресов")
    return list(addresses.values())


def upsert_addresses(session: Session, rows: list[dict]) -> None:
    """Обновить по PK=address_text; сохранить id, не затирать индекс и тип дома null."""
    for batch in batched(rows, 500):
        statement = insert(AddressRow).values(list(batch))
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[AddressRow.address_text],
                set_={
                    "latitude": statement.excluded.latitude,
                    "longitude": statement.excluded.longitude,
                    "city": statement.excluded.city,
                    "street": statement.excluded.street,
                    "house": statement.excluded.house,
                    "postal_code": func.coalesce(
                        statement.excluded.postal_code, AddressRow.postal_code
                    ),
                    "is_private": func.coalesce(
                        statement.excluded.is_private, AddressRow.is_private
                    ),
                },
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--validate-only", action="store_true", help="Проверить файл без подключения к БД"
    )
    args = parser.parse_args()
    try:
        rows = read_addresses(args.file)
    except (OSError, ValueError, EOFError) as exc:
        parser.exit(1, f"Ошибка: {exc}\n")
    if not args.validate_only:
        with session_scope() as session:
            upsert_addresses(session, rows)
    print(
        json.dumps(
            {
                "addresses": len(rows),
                "with_postal_code": sum(r["postal_code"] is not None for r in rows),
                "with_city": sum(r["city"] is not None for r in rows),
                "written": not args.validate_only,
            }
        )
    )


if __name__ == "__main__":
    main()
