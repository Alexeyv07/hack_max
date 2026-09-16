"""Keyset-курсор для ленты (без OFFSET)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeedCursor:
    """Позиция в ленте, отсортированной по weight DESC, id DESC."""

    weight: float
    event_id: int


def encode_feed_cursor(cursor: FeedCursor) -> str:
    raw = f"{cursor.weight:.6f}:{cursor.event_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_feed_cursor(token: str) -> FeedCursor:
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        weight_s, id_s = raw.split(":", 1)
        return FeedCursor(weight=float(weight_s), event_id=int(id_s))
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("Некорректный cursor ленты") from exc


def is_after_cursor(*, weight: float, event_id: int, cursor: FeedCursor) -> bool:
    """True, если элемент идёт строго после cursor в порядке weight DESC, id DESC."""
    if weight < cursor.weight:
        return True
    return weight == cursor.weight and event_id < cursor.event_id
