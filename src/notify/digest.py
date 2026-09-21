"""Суточная суммаризация сообщений домовых чатов."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from notify.chat_source import ChatMessage
from notify.db import NotifyDigestRow
from project.config import NotifyConfig
from user_chat.db import ChatRow


@dataclass(frozen=True, slots=True)
class DigestTarget:
    """Домовой MAX-чат, для которого пора проверить новые сообщения."""

    chat_id: int


def digest_scheduled_at(chat_id: int, day: date, config: NotifyConfig) -> datetime:
    """Стабильное время около ``digest_hour`` с детерминированным jitter по chat_id."""
    timezone = ZoneInfo(config.timezone)
    base = datetime.combine(day, time(hour=config.digest_hour), tzinfo=timezone)
    jitter = max(0, int(config.digest_jitter_minutes))
    if jitter == 0:
        return base

    digest = hashlib.blake2b(str(chat_id).encode(), digest_size=8).digest()
    bucket = int.from_bytes(digest, byteorder="big", signed=False)
    offset_minutes = bucket % (2 * jitter + 1) - jitter
    return base + timedelta(minutes=offset_minutes)


def list_due_digest_targets(
    session: Session,
    *,
    now: datetime,
    config: NotifyConfig,
) -> list[DigestTarget]:
    """Вернуть домовые чаты, у которых сегодня уже наступило время summary."""
    local_now = _aware_utc(now).astimezone(ZoneInfo(config.timezone))
    today = local_now.date()

    rows = session.execute(
        select(ChatRow.chat_id, NotifyDigestRow.last_digest_date)
        .outerjoin(NotifyDigestRow, NotifyDigestRow.chat_id == ChatRow.chat_id)
        .where(ChatRow.chat_type == "chat")
        .order_by(ChatRow.chat_id)
    ).all()

    due: list[DigestTarget] = []
    for chat_id, last_digest_date in rows:
        if last_digest_date == today:
            continue
        if local_now < digest_scheduled_at(chat_id, today, config):
            continue
        due.append(DigestTarget(chat_id=chat_id))
    return due


def digest_cursor(session: Session, chat_id: int) -> datetime | None:
    """Время последнего сообщения, вошедшего в успешно отправленную суммаризацию."""
    state = session.get(NotifyDigestRow, chat_id)
    if state is None or state.last_message_at is None:
        return None
    return _aware_utc(state.last_message_at)


def normalize_messages(messages: Sequence[ChatMessage]) -> list[ChatMessage]:
    """Убрать пустые сообщения, нормализовать пробелы и отсортировать по времени."""
    normalized: list[ChatMessage] = []
    for message in messages:
        text = " ".join(message.text.split())
        if not text:
            continue
        normalized.append(
            ChatMessage(
                text=text,
                created_at=_aware_utc(message.created_at),
            )
        )
    normalized.sort(key=lambda message: message.created_at)
    return normalized


def build_template_digest(messages: Sequence[ChatMessage]) -> str | None:
    """Экстрактивный fallback без LLM: несколько последних неповторяющихся сообщений."""
    if not messages:
        return None

    selected: list[str] = []
    seen: set[str] = set()
    for message in reversed(messages):
        text = _compact(message.text, limit=220)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        selected.append(text)
        if len(selected) == 5:
            break

    if not selected:
        return None
    selected.reverse()
    return "\n".join(f"• {text}" for text in selected)


def decorate_digest(text: str, *, bot_link: str | None) -> str:
    """Добавить обязательный тег и ссылку на бота к готовому summary."""
    body = text.strip()
    if body.startswith("#итого"):
        body = body.removeprefix("#итого").lstrip()

    parts = ["#итого"]
    if body:
        parts.extend(("", body))
    if bot_link:
        parts.extend(("", f"Присоединиться к боту: {bot_link}"))
    return "\n".join(parts)


def mark_digest_done(
    session: Session,
    *,
    chat_id: int,
    day: date,
    sent_at: datetime | None,
    last_message_at: datetime | None = None,
) -> None:
    """Зафиксировать запуск дня; cursor двигается только после успешной отправки."""
    state = session.get(NotifyDigestRow, chat_id)
    if state is None:
        state = NotifyDigestRow(chat_id=chat_id)
        session.add(state)

    state.last_digest_date = day
    if sent_at is not None:
        state.last_sent_at = _aware_utc(sent_at)
    if last_message_at is not None:
        state.last_message_at = _aware_utc(last_message_at)
    session.flush()


def _compact(value: str, *, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
