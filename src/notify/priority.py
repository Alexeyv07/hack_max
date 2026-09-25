"""Личные приоритетные уведомления и их повтор до подтверждения."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from auth.db.user import UserRow
from events.db.event import EventRow
from notify.db import NotifyCursorRow, NotifyDeliveryRow
from user_chat.db import ChatRow, users_chat

PRIORITY_CURSOR = "priority"
# Только высшая категория: обычные события (2 и 3) остаются в ленте.
_PRIORITY_IMPORTANCE = (1,)


@dataclass(frozen=True, slots=True)
class PriorityDelivery:
    """Одна доставка Event в личный диалог конкретного пользователя."""

    delivery_id: int
    user_id: int
    max_user_id: int
    chat_id: int
    event_id: int
    title: str
    body: str
    importance: int


def enqueue_new_priority_deliveries(
    session: Session,
    *,
    cursor_name: str = PRIORITY_CURSOR,
) -> int:
    """Создать delivery для новых Event и сдвинуть cursor после обработки пачки.

    На самом первом запуске cursor ставится на текущий max(events.id), чтобы включение
    notify на существующей БД не разослало всю историческую ленту.
    """
    cursor = session.get(NotifyCursorRow, cursor_name)
    if cursor is None:
        latest_event_id = session.scalar(select(func.max(EventRow.id))) or 0
        session.add(NotifyCursorRow(name=cursor_name, last_event_id=int(latest_event_id)))
        session.flush()
        return 0

    events = list(
        session.scalars(
            select(EventRow).where(EventRow.id > cursor.last_event_id).order_by(EventRow.id)
        ).all()
    )
    if not events:
        return 0

    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    created = 0
    last_event_id = cursor.last_event_id

    for event in events:
        last_event_id = max(last_event_id, event.id)
        if event.importance not in _PRIORITY_IMPORTANCE:
            continue
        for user_id in _priority_recipient_user_ids(session, event):
            result = session.execute(
                insert(NotifyDeliveryRow)
                .values(user_id=user_id, event_id=event.id)
                .on_conflict_do_nothing(index_elements=["user_id", "event_id"])
            )
            created += int(result.rowcount == 1)

    cursor.last_event_id = last_event_id
    session.flush()
    return created


def list_due_priority_deliveries(
    session: Session,
    *,
    now: datetime,
    retry_interval_seconds: int,
) -> list[PriorityDelivery]:
    """Неподтверждённые доставки: первая отправка или retry после interval."""
    current = _aware_utc(now)
    retry_before = current - timedelta(seconds=max(1, retry_interval_seconds))

    rows = session.execute(
        select(NotifyDeliveryRow, UserRow, EventRow)
        .join(UserRow, UserRow.id == NotifyDeliveryRow.user_id)
        .join(EventRow, EventRow.id == NotifyDeliveryRow.event_id)
        .where(
            NotifyDeliveryRow.acked_at.is_(None),
            UserRow.chat_id.is_not(None),
            UserRow.notify_blocked_at.is_(None),
            EventRow.importance.in_(_PRIORITY_IMPORTANCE),
            or_(
                NotifyDeliveryRow.last_sent_at.is_(None),
                NotifyDeliveryRow.last_sent_at <= retry_before,
            ),
        )
        .order_by(NotifyDeliveryRow.id)
    ).all()

    return [
        PriorityDelivery(
            delivery_id=delivery.id,
            user_id=user.id,
            max_user_id=user.max_user_id,
            chat_id=int(user.chat_id),
            event_id=event.id,
            title=event.title,
            body=event.body,
            importance=event.importance,
        )
        for delivery, user, event in rows
        if user.chat_id is not None
    ]


def delivery_is_due(
    session: Session,
    *,
    delivery_id: int,
    now: datetime,
    retry_interval_seconds: int,
) -> bool:
    """Повторная проверка прямо перед send, чтобы ack не гонялся с scheduler."""
    row = session.get(NotifyDeliveryRow, delivery_id)
    if row is None or row.acked_at is not None:
        return False
    event = session.get(EventRow, row.event_id)
    if event is None or event.importance not in _PRIORITY_IMPORTANCE:
        return False
    user = session.get(UserRow, row.user_id)
    if user is None or user.notify_blocked_at is not None:
        return False
    if row.last_sent_at is None:
        return True
    retry_before = _aware_utc(now) - timedelta(seconds=max(1, retry_interval_seconds))
    return _aware_utc(row.last_sent_at) <= retry_before


def block_user_notifications(
    session: Session,
    *,
    user_id: int,
    blocked_at: datetime,
    reason: str,
) -> bool:
    """Отложить все личные доставки при постоянном отказе MAX без ложного ack."""
    user = session.get(UserRow, user_id)
    if user is None or user.notify_blocked_at is not None:
        return False
    user.notify_blocked_at = _aware_utc(blocked_at)
    user.notify_blocked_reason = reason
    session.flush()
    return True


def is_suspended_dialog_error(exc: Exception) -> bool:
    """Только подтверждённый 403 chat.denied/dialog.suspended, не сетевые сбои."""
    raw = getattr(exc, "raw", None)
    return (
        getattr(exc, "code", None) == 403
        and isinstance(raw, dict)
        and raw.get("code") == "chat.denied"
        and "error.dialog.suspended" in str(raw.get("message", ""))
    )


def mark_delivery_sent(
    session: Session,
    *,
    delivery_id: int,
    sent_at: datetime,
    message_mid: str | None = None,
) -> bool:
    """Зафиксировать только успешную отправку."""
    row = session.get(NotifyDeliveryRow, delivery_id)
    if row is None:
        return False
    current = _aware_utc(sent_at)
    if row.first_sent_at is None:
        row.first_sent_at = current
    row.last_sent_at = current
    row.attempts += 1
    if message_mid:
        row.last_message_mid = message_mid
    session.flush()
    return True


def delivery_last_message_mid(session: Session, *, delivery_id: int) -> str | None:
    """mid предыдущего сообщения в MAX для этой доставки (если уже слали)."""
    row = session.get(NotifyDeliveryRow, delivery_id)
    if row is None:
        return None
    mid = row.last_message_mid
    return str(mid) if mid else None


def acknowledge_delivery(
    session: Session,
    *,
    delivery_id: int,
    max_user_id: int,
    acked_at: datetime | None = None,
) -> bool:
    """Подтвердить delivery только пользователем, которому оно предназначено."""
    row = session.scalar(
        select(NotifyDeliveryRow)
        .join(UserRow, UserRow.id == NotifyDeliveryRow.user_id)
        .where(
            NotifyDeliveryRow.id == delivery_id,
            UserRow.max_user_id == max_user_id,
        )
    )
    if row is None:
        return False
    if row.acked_at is None:
        row.acked_at = _aware_utc(acked_at or datetime.now(UTC))
        session.flush()
    return True


def has_expandable_body(delivery: PriorityDelivery) -> bool:
    """Есть отдельный текст body, который имеет смысл скрывать под «Подробнее»."""
    title = _compact(delivery.title, limit=240)
    body = _compact(delivery.body, limit=3000)
    return bool(body) and body.casefold() != title.casefold()


def build_priority_text(
    delivery: PriorityDelivery,
    *,
    expanded: bool = False,
    docs_url: str | None = None,
) -> str:
    """Заголовок всегда виден; body по умолчанию скрыт (в MAX нет native spoiler).

    Раскрытие — через callback «Подробнее» / «Свернуть» (edit того же сообщения).
    """
    marker = "🔴" if delivery.importance == 1 else "🟠"
    title = _compact(delivery.title, limit=240)
    body = _compact(delivery.body, limit=3000)
    text = f"{marker} {title}"
    if has_expandable_body(delivery):
        if expanded:
            text = f"{text}\n\n{body}"
        else:
            text = f"{text}\n\n_Подробности скрыты — нажмите «Подробнее»._"
    if docs_url:
        # Markdown inline-ссылка, не кнопка клавиатуры.
        text = f"{text}\n\n[Как устроены уведомления?]({docs_url})"
    return text


def ack_payload(delivery_id: int) -> str:
    return f"notify:ack:{delivery_id}"


def expand_payload(delivery_id: int) -> str:
    return f"notify:expand:{delivery_id}"


def collapse_payload(delivery_id: int) -> str:
    return f"notify:collapse:{delivery_id}"


def parse_ack_payload(payload: str) -> int | None:
    return _parse_notify_id_payload(payload, "notify:ack:")


def parse_expand_payload(payload: str) -> int | None:
    return _parse_notify_id_payload(payload, "notify:expand:")


def parse_collapse_payload(payload: str) -> int | None:
    return _parse_notify_id_payload(payload, "notify:collapse:")


def _parse_notify_id_payload(payload: str, prefix: str) -> int | None:
    if not payload.startswith(prefix):
        return None
    raw = payload.removeprefix(prefix)
    if not raw.isdigit():
        return None
    delivery_id = int(raw)
    return delivery_id if delivery_id > 0 else None


def build_priority_keyboard(delivery: PriorityDelivery, *, expanded: bool = False) -> Any:
    """«Подробнее»/«Свернуть» + «Увидел». Docs — только в тексте сообщения."""
    from maxapi.types import CallbackButton
    from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    if has_expandable_body(delivery):
        if expanded:
            builder.row(
                CallbackButton(text="Свернуть", payload=collapse_payload(delivery.delivery_id))
            )
        else:
            builder.row(
                CallbackButton(text="Подробнее", payload=expand_payload(delivery.delivery_id))
            )
    builder.row(CallbackButton(text="Увидел", payload=ack_payload(delivery.delivery_id)))
    return builder.as_markup()


def _priority_recipient_user_ids(session: Session, event: EventRow) -> list[int]:
    if event.address_id is None or event.geo_by not in {"home", "street", "city"}:
        return []

    event_address = session.get(AddressRow, event.address_id)
    if event_address is None:
        return []

    chat_address = AddressRow.__table__.alias("notify_chat_address")
    query = (
        select(UserRow.id)
        .join(users_chat, users_chat.c.user_id == UserRow.id)
        .join(ChatRow, ChatRow.chat_id == users_chat.c.chat_id)
        .join(chat_address, chat_address.c.id == users_chat.c.address_id)
        .where(
            ChatRow.chat_type == "chat",
            UserRow.chat_id.is_not(None),
        )
    )

    if event.geo_by == "home":
        query = query.where(users_chat.c.address_id == event.address_id)
    elif event.geo_by == "street":
        if not event_address.city or not event_address.street:
            return []
        query = query.where(
            chat_address.c.city == event_address.city,
            chat_address.c.street == event_address.street,
        )
    else:
        if not event_address.city:
            return []
        query = query.where(chat_address.c.city == event_address.city)

    return list(session.scalars(query.distinct()).all())


def _compact(value: str, *, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
