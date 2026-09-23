"""Callback-кнопки личных уведомлений."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from maxapi import F

from notify.priority import acknowledge_delivery, parse_ack_payload
from project.database import session_scope
from project.logging_setup import get_logger

logger = get_logger(__name__)


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
        await ack(notification="Отмечено как увиденное" if acknowledged else None)
    except Exception:
        logger.debug("Не удалось подтвердить callback notify", exc_info=True)


def register_notify_commands(dp: Any, bot: Any) -> None:
    """Зарегистрировать только notify callback; остальные callbacks не перехватываем."""

    @dp.message_callback(F.callback.payload.startswith("notify:ack:"))
    async def on_notify_ack(event: Any) -> None:
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
