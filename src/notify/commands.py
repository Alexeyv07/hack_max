"""Callback-кнопки и демо-команды личных уведомлений."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from maxapi import F
from maxapi.filters.command import Command
from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from auth.db.user import UserRow
from auth.handlers.authorize import authorize_from_event, get_user_by_max_id
from events.db.event import EventRow
from notify.db import NotifyDeliveryRow
from notify.messaging import delete_message_quiet, sent_mid
from notify.priority import (
    PriorityDelivery,
    acknowledge_delivery,
    build_priority_keyboard,
    build_priority_text,
    mark_delivery_sent,
    parse_ack_payload,
    parse_collapse_payload,
    parse_expand_payload,
)
from project.config import get_settings
from project.database import session_scope
from project.logging_setup import get_logger

logger = get_logger(__name__)

_DEMO_TITLE = "Проверка уведомления"
_DEMO_BODY = (
    "Так выглядит важное сообщение о вашем доме: например, отключение воды "
    "или срочный ремонт рядом. Нажмите «Увидел», когда прочитаете."
)
_DEMO_ACK = "notify:demo:ack"
_DEMO_EXPAND = "notify:demo:expand"
_DEMO_COLLAPSE = "notify:demo:collapse"


def _demo_delivery() -> PriorityDelivery:
    return PriorityDelivery(
        delivery_id=0,
        user_id=0,
        max_user_id=0,
        chat_id=0,
        event_id=0,
        title=_DEMO_TITLE,
        body=_DEMO_BODY,
        importance=1,
    )


def _demo_keyboard(*, expanded: bool) -> Any:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="Свернуть" if expanded else "Подробнее",
            payload=_DEMO_COLLAPSE if expanded else _DEMO_EXPAND,
        )
    )
    builder.row(CallbackButton(text="Увидел", payload=_DEMO_ACK))
    return builder.as_markup()


async def _finish_ack_callback(event: Any, *, acknowledged: bool) -> None:
    if acknowledged:
        edit = getattr(event, "edit", None)
        if callable(edit):
            try:
                await edit(
                    attachments=[],
                    notification="Отмечено как увиденное",
                    notify=False,
                )
                return
            except Exception:
                logger.debug("Не удалось обновить кнопку notify", exc_info=True)

    ack = getattr(event, "ack", None)
    if not callable(ack):
        return
    try:
        await ack(notification="Отмечено как увиденное" if acknowledged else "…")
    except Exception:
        logger.debug("Не удалось подтвердить callback notify", exc_info=True)


async def _delete_user_command(bot: Any, event: Any) -> None:
    mid = getattr(getattr(getattr(event, "message", None), "body", None), "mid", None)
    await delete_message_quiet(bot, str(mid) if mid else None)


def _pick_demo_event(session: Session) -> EventRow | None:
    event = session.scalar(
        select(EventRow).where(EventRow.importance == 1).order_by(func.random()).limit(1)
    )
    if event is not None:
        return event
    return session.scalar(select(EventRow).order_by(func.random()).limit(1))


def _ensure_demo_delivery(session: Session, *, user_id: int, event_id: int) -> NotifyDeliveryRow:
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    session.execute(
        insert(NotifyDeliveryRow)
        .values(user_id=user_id, event_id=event_id)
        .on_conflict_do_nothing(index_elements=["user_id", "event_id"])
    )
    delivery = session.scalar(
        select(NotifyDeliveryRow).where(
            NotifyDeliveryRow.user_id == user_id,
            NotifyDeliveryRow.event_id == event_id,
        )
    )
    assert delivery is not None
    delivery.acked_at = None
    session.flush()
    return delivery


def _delivery_view(
    session: Session, *, delivery_id: int, max_user_id: int
) -> PriorityDelivery | None:
    row = session.execute(
        select(NotifyDeliveryRow, EventRow, UserRow)
        .join(EventRow, EventRow.id == NotifyDeliveryRow.event_id)
        .join(UserRow, UserRow.id == NotifyDeliveryRow.user_id)
        .where(
            NotifyDeliveryRow.id == delivery_id,
            UserRow.max_user_id == max_user_id,
        )
    ).first()
    if row is None:
        return None
    delivery, event, user = row
    if user.chat_id is None:
        return None
    return PriorityDelivery(
        delivery_id=delivery.id,
        user_id=user.id,
        max_user_id=user.max_user_id,
        chat_id=int(user.chat_id),
        event_id=event.id,
        title=event.title or _DEMO_TITLE,
        body=event.body or "",
        importance=1 if event.importance not in {1, 2} else event.importance,
    )


async def _toggle_notify_body(event: Any, *, delivery_id: int, expanded: bool) -> None:
    max_user_id = int(event.callback.user.user_id)
    docs = get_settings().docs.notifications_url
    with session_scope() as session:
        delivery = _delivery_view(session, delivery_id=delivery_id, max_user_id=max_user_id)
    if delivery is None:
        ack = getattr(event, "ack", None)
        if callable(ack):
            await ack(notification="Уведомление недоступно")
        return
    text = build_priority_text(delivery, expanded=expanded, docs_url=docs)
    keyboard = build_priority_keyboard(delivery, expanded=expanded)
    edit = getattr(event, "edit", None)
    if callable(edit):
        try:
            await edit(
                text=text,
                attachments=[keyboard],
                format="markdown",
                notify=False,
                notification="Подробности" if expanded else "Скрыто",
            )
            return
        except Exception:
            logger.debug("Не удалось переключить body notify", exc_info=True)
    mid = getattr(getattr(getattr(event, "message", None), "body", None), "mid", None)
    if mid:
        try:
            from project.max_runtime import get_max_bot

            bot = get_max_bot()
            if bot is not None:
                await bot.edit_message(
                    str(mid),
                    text=text,
                    attachments=[keyboard],
                    format="markdown",
                    notify=False,
                    brand_image=False,
                )
        except Exception:
            logger.debug("Не удалось edit notify mid=%s", mid, exc_info=True)
    ack = getattr(event, "ack", None)
    if callable(ack):
        await ack(notification="…")


async def _toggle_demo_body(event: Any, *, expanded: bool) -> None:
    docs = get_settings().docs.notifications_url
    delivery = _demo_delivery()
    text = build_priority_text(delivery, expanded=expanded, docs_url=docs)
    keyboard = _demo_keyboard(expanded=expanded)
    edit = getattr(event, "edit", None)
    if callable(edit):
        try:
            await edit(
                text=text,
                attachments=[keyboard],
                format="markdown",
                notify=False,
                notification="Подробности" if expanded else "Скрыто",
            )
            return
        except Exception:
            logger.debug("Не удалось переключить demo notify", exc_info=True)
    ack = getattr(event, "ack", None)
    if callable(ack):
        await ack(notification="…")


async def _send_demo_notify(bot: Any, *, max_user_id: int, chat_id: int | None) -> None:
    docs = get_settings().docs.notifications_url
    with session_scope() as session:
        user = get_user_by_max_id(session, max_user_id)
        if user is None:
            return
        event = _pick_demo_event(session)
        if event is None:
            delivery = _demo_delivery()
            text = build_priority_text(delivery, expanded=False, docs_url=docs)
            markup = _demo_keyboard(expanded=False)
            recipient: dict[str, int] = (
                {"chat_id": int(chat_id)}
                if chat_id is not None and int(chat_id) > 0
                else {"user_id": max_user_id}
            )
            await bot.send_message(
                **recipient,
                text=text,
                attachments=[markup],
                format="markdown",
                brand_image=False,
            )
            return

        delivery_row = _ensure_demo_delivery(session, user_id=user.id, event_id=event.id)
        previous_mid = delivery_row.last_message_mid
        delivery = PriorityDelivery(
            delivery_id=delivery_row.id,
            user_id=user.id,
            max_user_id=user.max_user_id,
            chat_id=int(chat_id or user.chat_id or 0),
            event_id=event.id,
            title=event.title or _DEMO_TITLE,
            body=event.body or _DEMO_BODY,
            importance=1 if event.importance not in {1, 2} else event.importance,
        )
        text = build_priority_text(delivery, expanded=False, docs_url=docs)
        markup = build_priority_keyboard(delivery, expanded=False)
        target_chat = chat_id or user.chat_id
        recipient = (
            {"chat_id": int(target_chat)}
            if target_chat is not None and int(target_chat) > 0
            else {"user_id": max_user_id}
        )
        delivery_id = delivery.delivery_id

    if previous_mid:
        try:
            await bot.edit_message(
                previous_mid,
                text=text,
                attachments=[markup],
                format="markdown",
                notify=False,
            )
            with session_scope() as session:
                mark_delivery_sent(
                    session,
                    delivery_id=delivery_id,
                    sent_at=datetime.now(UTC),
                    message_mid=previous_mid,
                )
            return
        except Exception:
            logger.debug("Не удалось edit демо-notify mid=%s", previous_mid, exc_info=True)
            await delete_message_quiet(bot, previous_mid)

    result = await bot.send_message(
        **recipient,
        text=text,
        attachments=[markup],
        format="markdown",
        brand_image=False,
    )
    with session_scope() as session:
        mark_delivery_sent(
            session,
            delivery_id=delivery_id,
            sent_at=datetime.now(UTC),
            message_mid=sent_mid(result),
        )


def register_notify_commands(dp: Any, bot: Any) -> None:
    """Notify callbacks и команда /get_notify для демо на хакатоне."""

    @dp.message_callback(F.callback.payload.startswith("notify:expand:"))
    async def on_notify_expand(event: Any) -> None:
        delivery_id = parse_expand_payload(str(getattr(event.callback, "payload", "") or ""))
        if delivery_id is None:
            return
        await _toggle_notify_body(event, delivery_id=delivery_id, expanded=True)

    @dp.message_callback(F.callback.payload.startswith("notify:collapse:"))
    async def on_notify_collapse(event: Any) -> None:
        delivery_id = parse_collapse_payload(str(getattr(event.callback, "payload", "") or ""))
        if delivery_id is None:
            return
        await _toggle_notify_body(event, delivery_id=delivery_id, expanded=False)

    @dp.message_callback(F.callback.payload == _DEMO_EXPAND)
    async def on_demo_expand(event: Any) -> None:
        await _toggle_demo_body(event, expanded=True)

    @dp.message_callback(F.callback.payload == _DEMO_COLLAPSE)
    async def on_demo_collapse(event: Any) -> None:
        await _toggle_demo_body(event, expanded=False)

    @dp.message_callback(F.callback.payload == _DEMO_ACK)
    async def on_demo_ack(event: Any) -> None:
        await _finish_ack_callback(event, acknowledged=True)

    @dp.message_callback(F.callback.payload.startswith("notify:ack:"))
    async def on_notify_ack(event: Any, context: Any) -> None:
        delivery_id = parse_ack_payload(str(getattr(event.callback, "payload", "") or ""))
        if delivery_id is None:
            await _finish_ack_callback(event, acknowledged=False)
            return
        max_user_id = int(event.callback.user.user_id)
        with session_scope() as session:
            acknowledged = acknowledge_delivery(
                session,
                delivery_id=delivery_id,
                max_user_id=max_user_id,
                acked_at=datetime.now(UTC),
            )
        await _finish_ack_callback(event, acknowledged=acknowledged)
        if not acknowledged:
            logger.warning(
                "Отклонён notify ack delivery_id=%s max_user_id=%s",
                delivery_id,
                max_user_id,
            )

    @dp.message_callback(F.callback.payload.startswith("notify:approval:"))
    async def on_obsolete_approval(event: Any) -> None:
        """Старые кнопки заявки больше не выполняют никаких действий в MAX/БД."""
        edit = getattr(event, "edit", None)
        if callable(edit):
            try:
                await edit(
                    attachments=[],
                    notification="Заявки заменены проверкой членства в чате",
                    notify=False,
                )
                return
            except Exception:
                logger.debug("Не удалось убрать старые кнопки одобрения", exc_info=True)
        ack = getattr(event, "ack", None)
        if callable(ack):
            await ack(notification="Эта заявка больше не используется")

    @dp.message_created(Command("get_notify"))
    async def on_get_notify(event: Any) -> None:
        """Случайное (или демо) уведомление — чтобы судья увидел формат пуша."""
        user = await asyncio.to_thread(authorize_from_event, event)
        await _delete_user_command(bot, event)
        if user is None:
            return
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            recipient = getattr(getattr(event, "message", None), "recipient", None)
            chat_id = getattr(recipient, "chat_id", None)
        try:
            await _send_demo_notify(bot, max_user_id=user.max_user_id, chat_id=chat_id)
        except Exception:
            logger.exception("Не удалось отправить демо-уведомление")
