"""Дедуп выдачи ленты: fan-out :addr: и одинаковый title/body."""

from __future__ import annotations

import re
from typing import Literal

from events.models.event import Event
from parser_common.text_features import collapse_ws

_ADDR_SUFFIX = re.compile(r":addr:\d+$", re.IGNORECASE)


def sibling_group_key(*, source: str, source_msg_id: str | None) -> str | None:
    """Группа MC fan-out: outlet:id:addr:N → outlet:id."""
    if not source_msg_id:
        return None
    base = _ADDR_SUFFIX.sub("", source_msg_id.strip())
    if not base:
        return None
    return f"{source}|{base}"


def content_group_key(*, title: str | None, body: str) -> str | None:
    """Одинаковый заголовок или (если title пуст/короткий) начало body."""
    t = collapse_ws(title or "")
    if len(t) >= 12:
        return f"t:{t.casefold()}"
    b = collapse_ws(body or "")
    if len(b) >= 40:
        return f"b:{b[:400].casefold()}"
    return None


def _keep_better(
    current: Event,
    challenger: Event,
    *,
    prefer: Literal["distance", "weight"],
) -> Event:
    if prefer == "distance":
        d_cur = current.distance_m if current.distance_m is not None else 1e18
        d_new = challenger.distance_m if challenger.distance_m is not None else 1e18
        if d_new < d_cur - 1e-6:
            return challenger
        if abs(d_new - d_cur) <= 1e-6 and (challenger.weight, challenger.id) > (
            current.weight,
            current.id,
        ):
            return challenger
        return current
    if (challenger.weight, challenger.id) > (current.weight, current.id):
        return challenger
    return current


def _dedupe_by_key(
    events: list[Event],
    *,
    key_fn,
    prefer: Literal["distance", "weight"],
) -> list[Event]:
    best: dict[str, Event] = {}
    for event in events:
        key = key_fn(event)
        if key is None:
            continue
        prev = best.get(key)
        best[key] = event if prev is None else _keep_better(prev, event, prefer=prefer)

    out: list[Event] = []
    seen: set[str] = set()
    for event in events:
        key = key_fn(event)
        if key is None:
            out.append(event)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(best[key])
    return out


def dedupe_feed_events(
    events: list[Event],
    *,
    prefer: Literal["distance", "weight"] = "weight",
) -> list[Event]:
    """
    Одна карточка на группу: сначала MC ``:addr:`` siblings, затем title/body.
    """
    if len(events) <= 1:
        return events

    after_siblings = _dedupe_by_key(
        events,
        key_fn=lambda e: sibling_group_key(source=e.source, source_msg_id=e.source_msg_id),
        prefer=prefer,
    )
    return _dedupe_by_key(
        after_siblings,
        key_fn=lambda e: content_group_key(title=e.title, body=e.body),
        prefer=prefer,
    )
