"""Фоновый worker личных priority-уведомлений."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from notify.priority import (
    PriorityDelivery,
    ack_payload,
    build_priority_text,
    delivery_is_due,
    enqueue_new_priority_deliveries,
    list_due_priority_deliveries,
    mark_delivery_sent,
)
from project.config import NotifyConfig, get_settings
from project.database import get_session_factory
from project.logging_setup import get_logger
from project.max_runtime import get_max_bot

logger = get_logger(__name__)

PriorityKeyboardFactory = Callable[[PriorityDelivery], Any]


def _build_priority_keyboard(delivery: PriorityDelivery) -> Any:
    from maxapi.types import CallbackButton
    from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="Увидел", payload=ack_payload(delivery.delivery_id)))
    return builder.as_markup()


async def run_priority_cycle(
    bot: Any,
    *,
    now: datetime | None = None,
    config: NotifyConfig | None = None,
    session_factory: sessionmaker[Session] | None = None,
    keyboard_factory: PriorityKeyboardFactory = _build_priority_keyboard,
) -> int:
    """Создать новые personal deliveries и отправить все due/retry."""
    cfg = config or get_settings().notify
    current = now or datetime.now(UTC)
    factory = session_factory or get_session_factory()

    with factory() as session:
        enqueue_new_priority_deliveries(session)
        session.commit()

    with factory() as session:
        due = list_due_priority_deliveries(
            session,
            now=current,
            retry_interval_seconds=cfg.retry_interval_seconds,
        )

    sent = 0
    for delivery in due:
        with factory() as session:
            if not delivery_is_due(
                session,
                delivery_id=delivery.delivery_id,
                now=current,
                retry_interval_seconds=cfg.retry_interval_seconds,
            ):
                continue

        try:
            await bot.send_message(
                chat_id=delivery.chat_id,
                text=build_priority_text(delivery),
                attachments=[keyboard_factory(delivery)],
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Не удалось отправить личное priority-уведомление",
                extra={
                    "delivery_id": delivery.delivery_id,
                    "event_id": delivery.event_id,
                    "user_id": delivery.user_id,
                },
            )
            continue

        with factory() as session:
            if mark_delivery_sent(
                session,
                delivery_id=delivery.delivery_id,
                sent_at=current,
            ):
                session.commit()
                sent += 1

    return sent


async def run_notify_worker() -> None:
    """Периодически запускать личные уведомления; включается NOTIFY_ENABLED=true."""
    cfg = get_settings().notify
    if not cfg.enabled:
        logger.info("Notify worker выключен (NOTIFY_ENABLED=false)")
        return

    logger.info(
        "Notify worker запущен: retry=%ss poll=%ss",
        cfg.retry_interval_seconds,
        cfg.poll_interval_seconds,
    )
    while True:
        bot = get_max_bot()
        if bot is None:
            logger.debug("Notify worker ждёт запуска MAX bot")
        else:
            await run_priority_cycle(bot, config=cfg)
        await asyncio.sleep(max(1, cfg.poll_interval_seconds))
