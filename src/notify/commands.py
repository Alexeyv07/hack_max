"""Callback-кнопки личных уведомлений."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from maxapi import F

from notify.priority import acknowledge_delivery, parse_ack_payload
from project.database import session_scope
from project.logging_setup import get_logger

logger = get_logger(__name__)


async def _ack_callback(event: Any) -> None:
    ack = getattr(event, "ack", None)
    if not callable(ack):
        return
    try:
        await ack()
    except Exception:
        logger.debug("Не удалось подтвердить callback notify", exc_info=True)


def register_notify_commands(dp: Any) -> None:
    """Зарегистрировать только notify callback; остальные callbacks не перехватываем."""

    @dp.message_callback(F.callback.payload.startswith("notify:ack:"))
    async def on_notify_ack(event: Any) -> None:
        await _ack_callback(event)
        delivery_id = parse_ack_payload(str(getattr(event.callback, "payload", "") or ""))
        if delivery_id is None:
            return
        max_user_id = int(event.callback.user.user_id)
        with session_scope() as session:
            acknowledged = acknowledge_delivery(
                session,
                delivery_id=delivery_id,
                max_user_id=max_user_id,
                acked_at=datetime.now(UTC),
            )
        if not acknowledged:
            logger.warning(
                "Отклонён notify ack delivery_id=%s max_user_id=%s",
                delivery_id,
                max_user_id,
            )
