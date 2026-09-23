"""Минимальный фильтр шума перед ParserCandidate (без LLM / allowlist).

Пропускаем почти всё содержательное; бытовуху отсекает classify (importance=3).
Жёсткий drop только: бот, /команды, пусто без медиа, стикер-only, флуд-повтор.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum

from parse_chat.models.message import RawChatMessage

_WS = re.compile(r"\s+")

# Короткие «пустые» приветствия целиком (не режем длинные мнения со словом «привет»).
_DEFAULT_GREETING_ONLY: tuple[str, ...] = (
    "привет",
    "здравствуйте",
    "здарова",
    "добрый день",
    "добрый вечер",
    "доброе утро",
    "привет всем",
    "всем привет",
    "ку",
    "хай",
    "+",
    "ок",
    "окей",
    "ладно",
)


class FilterRejectReason(StrEnum):
    BOT_SENDER = "bot_sender"
    COMMAND = "command"
    EMPTY = "empty"
    STICKER_ONLY = "sticker_only"
    GREETING_ONLY = "greeting_only"
    FLOOD = "flood"


@dataclass(frozen=True, slots=True)
class FilterConfig:
    min_chars: int = 3
    flood_window_seconds: int = 90
    flood_max_repeats: int = 3
    greeting_only: tuple[str, ...] = _DEFAULT_GREETING_ONLY
    # Совместимость со старым конфигом (игнорируются).
    min_chars_update: int = 3
    recent_context_seconds: int = 0
    allowlist: tuple[str, ...] = ()
    denylist: tuple[str, ...] = ()
    update_hints: tuple[str, ...] = ()
    min_letter_ratio: float = 0.0
    max_urls: int = 99


@dataclass(frozen=True, slots=True)
class FilterVerdict:
    accepted: bool
    reason: FilterRejectReason | None = None
    signal: str | None = None


def _norm_text(text: str) -> str:
    return _WS.sub(" ", text.lower().replace("ё", "е")).strip()


class FloodTracker:
    """Повтор того же текста от user в чате за окно."""

    def __init__(self) -> None:
        self._hits: dict[tuple[int, int, str], deque[float]] = defaultdict(deque)

    def is_flood(
        self,
        *,
        chat_id: int,
        sender_user_id: int,
        text_norm: str,
        window_seconds: int,
        max_repeats: int,
        now: float | None = None,
    ) -> bool:
        if max_repeats <= 0 or window_seconds <= 0 or not text_norm:
            return False
        ts = now if now is not None else time.monotonic()
        key = (chat_id, sender_user_id, text_norm)
        bucket = self._hits[key]
        cutoff = ts - window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(ts)
        return len(bucket) > max_repeats

    def clear(self) -> None:
        self._hits.clear()


# Оставлены для совместимости импортов/тестов; в permissive-режиме не используются.
class ChatActivityTracker:
    def __init__(self) -> None:
        self._last_accepted: dict[int, float] = {}

    def mark_accepted(self, chat_id: int, *, now: float | None = None) -> None:
        self._last_accepted[chat_id] = now if now is not None else time.monotonic()

    def recently_active(
        self,
        chat_id: int,
        *,
        window_seconds: int,
        now: float | None = None,
    ) -> bool:
        return False

    def clear(self) -> None:
        self._last_accepted.clear()


_FLOOD = FloodTracker()
_ACTIVITY = ChatActivityTracker()


def get_flood_tracker() -> FloodTracker:
    return _FLOOD


def get_activity_tracker() -> ChatActivityTracker:
    return _ACTIVITY


def _is_greeting_only(text_norm: str, greetings: tuple[str, ...]) -> bool:
    if not text_norm or not greetings:
        return False
    # только знаки препинания вокруг приветствия
    compact = re.sub(r"[^\w\s]+", " ", text_norm, flags=re.UNICODE)
    compact = _WS.sub(" ", compact).strip()
    return compact in {_norm_text(g) for g in greetings}


def filter_message(
    message: RawChatMessage,
    config: FilterConfig,
    *,
    flood: FloodTracker | None = None,
    activity: ChatActivityTracker | None = None,
    now: float | None = None,
) -> FilterVerdict:
    """
    Permissive: почти всё в normalize/classify.

    Drop только очевидный мусор. Важность / лента — у ML classify.
    """
    del activity  # не используем в permissive-режиме

    if message.sender_is_bot:
        return FilterVerdict(False, FilterRejectReason.BOT_SENDER)

    text = (message.text or "").strip()
    if text.startswith("/"):
        return FilterVerdict(False, FilterRejectReason.COMMAND)

    has_image = bool(message.image_url)
    if not text and not has_image:
        if message.has_attachments:
            return FilterVerdict(False, FilterRejectReason.STICKER_ONLY)
        return FilterVerdict(False, FilterRejectReason.EMPTY)

    text_norm = _norm_text(text) if text else ""
    if text and not has_image and _is_greeting_only(text_norm, config.greeting_only):
        return FilterVerdict(False, FilterRejectReason.GREETING_ONLY)

    if text and not has_image and len(text_norm) < config.min_chars:
        # слишком короткое без фото — обычно «ок»/«+»; greeting_only уже покрыл часть
        return FilterVerdict(False, FilterRejectReason.GREETING_ONLY)

    sender_id = message.sender_user_id
    if sender_id is not None and text_norm:
        tracker = flood if flood is not None else _FLOOD
        if tracker.is_flood(
            chat_id=message.chat_id,
            sender_user_id=sender_id,
            text_norm=text_norm,
            window_seconds=config.flood_window_seconds,
            max_repeats=config.flood_max_repeats,
            now=now,
        ):
            return FilterVerdict(False, FilterRejectReason.FLOOD)

    if has_image and text:
        signal = "text_image"
    elif has_image:
        signal = "image"
    else:
        signal = "text"
    return FilterVerdict(True, signal=signal)
