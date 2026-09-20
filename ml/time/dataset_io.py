"""Загрузка JSONL для time-window (active_from / active_to относительно reference)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TimeExample:
    text: str
    reference: datetime
    active_from: datetime | None
    active_to: datetime | None
    source: str | None = None

    @property
    def has_from(self) -> bool:
        return self.active_from is not None

    @property
    def has_to(self) -> bool:
        return self.active_to is not None

    @property
    def from_offset_hours(self) -> float | None:
        if self.active_from is None:
            return None
        return _hours_between(self.reference, self.active_from)

    @property
    def to_offset_hours(self) -> float | None:
        if self.active_to is None:
            return None
        return _hours_between(self.reference, self.active_to)


def _parse_dt(value: object, *, field: str, loc: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{loc}: поле {field} должно быть ISO-8601 строкой")
    text = value.strip()
    # Python 3.12: fromisoformat понимает +03:00; Z → +00:00
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{loc}: не разобрать {field}={value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _parse_optional_dt(value: object, *, field: str, loc: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _parse_dt(value, field=field, loc=loc)


def _hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600.0


def _fmt_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def load_jsonl(path: Path) -> list[TimeExample]:
    rows: list[TimeExample] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            loc = f"{path}:{line_no}"
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{loc}: битый JSON") from exc
            text = str(raw.get("text") or "").strip()
            if not text:
                raise ValueError(f"{loc}: пустой text")
            if "reference" not in raw:
                raise ValueError(f"{loc}: нет reference")
            reference = _parse_dt(raw["reference"], field="reference", loc=loc)
            active_from = _parse_optional_dt(raw.get("active_from"), field="active_from", loc=loc)
            active_to = _parse_optional_dt(raw.get("active_to"), field="active_to", loc=loc)
            if active_from is not None and active_to is not None and active_from > active_to:
                raise ValueError(f"{loc}: active_from > active_to")
            source = raw.get("source")
            rows.append(
                TimeExample(
                    text=text,
                    reference=reference,
                    active_from=active_from,
                    active_to=active_to,
                    source=str(source) if source is not None else None,
                )
            )
    if not rows:
        raise ValueError(f"Пустой датасет: {path}")
    return rows


def write_jsonl(path: Path, rows: list[TimeExample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            payload: dict[str, object] = {
                "text": row.text,
                "active_from": _fmt_dt(row.active_from),
                "active_to": _fmt_dt(row.active_to),
                "reference": _fmt_dt(row.reference),
            }
            if row.source is not None:
                payload["source"] = row.source
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def bound_counts(rows: list[TimeExample]) -> dict[str, int]:
    return {
        "both": sum(1 for r in rows if r.has_from and r.has_to),
        "from_only": sum(1 for r in rows if r.has_from and not r.has_to),
        "to_only": sum(1 for r in rows if r.has_to and not r.has_from),
        "neither": sum(1 for r in rows if not r.has_from and not r.has_to),
        "total": len(rows),
    }


def offsets_to_datetimes(
    reference: datetime,
    *,
    has_from: bool,
    has_to: bool,
    from_offset_hours: float,
    to_offset_hours: float,
) -> tuple[datetime | None, datetime | None]:
    """Inference helper: offsets → active_from / active_to."""
    from datetime import timedelta

    active_from = reference + timedelta(hours=float(from_offset_hours)) if has_from else None
    active_to = reference + timedelta(hours=float(to_offset_hours)) if has_to else None
    return active_from, active_to
