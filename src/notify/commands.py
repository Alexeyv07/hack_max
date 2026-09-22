"""Callback-кнопки личных уведомлений."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from maxapi import F

from notify.admin_approval import (
    approve_admin_request,
    get_admin_approval,
    parse_approval_payload,
    reject_admin_request,
)
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


async def _finish_approval_callback(
    event: Any,
    *,
    notification: str,
    clear_buttons: bool,
) -> None:
    if clear_buttons:
        edit = getattr(event, "edit", None)
        if callable(edit):
            try:
                await edit(attachments=[], notification=notification, notify=False)
                return
            except Exception:
                logger.debug("Не удалось обновить admin-approval сообщение", exc_info=True)

    ack = getattr(event, "ack", None)
    if not callable(ack):
        return
    try:
        await ack(notification=notification)
    except Exception:
        logger.debug("Не удалось подтвердить admin-approval callback", exc_info=True)


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
    async def on_admin_approval(event: Any) -> None:
        parsed = parse_approval_payload(str(getattr(event.callback, "payload", "") or ""))
        if parsed is None:
            await _finish_approval_callback(
                event, notification="Некорректная заявка", clear_buttons=False
            )
            return

        action, request_id = parsed
        max_user_id = int(event.callback.user.user_id)
        with session_scope() as session:
            approval = get_admin_approval(
                session,
                request_id=request_id,
                admin_max_user_id=max_user_id,
            )
        if approval is None:
            await _finish_approval_callback(
                event, notification="Заявка уже обработана", clear_buttons=True
            )
            return

        try:
            member = await bot.get_chat_member(approval.chat_id, max_user_id)
        except Exception:
            logger.exception(
                "Не удалось проверить права администратора",
                extra={"request_id": request_id, "chat_id": approval.chat_id},
            )
            await _finish_approval_callback(
                event,
                notification="Не удалось проверить права. Попробуйте ещё раз.",
                clear_buttons=False,
            )
            return

        if member is None or not (
            getattr(member, "is_admin", False) or getattr(member, "is_owner", False)
        ):
            await _finish_approval_callback(
                event,
                notification="Подтвердить заявку может только администратор чата",
                clear_buttons=False,
            )
            return

        if action == "approve":
            try:
                requester_member = await bot.get_chat_member(
                    approval.chat_id, approval.requester_max_user_id
                )
                if requester_member is None:
                    result = await bot.add_chat_members(
                        approval.chat_id, [approval.requester_max_user_id]
                    )
                    if not getattr(result, "success", False):
                        await _finish_approval_callback(
                            event,
                            notification="MAX не смог добавить пользователя в чат",
                            clear_buttons=False,
                        )
                        return
            except Exception:
                logger.exception(
                    "Не удалось добавить пользователя после admin approve",
                    extra={"request_id": request_id, "chat_id": approval.chat_id},
                )
                await _finish_approval_callback(
                    event,
                    notification="Не удалось добавить пользователя. Попробуйте ещё раз.",
                    clear_buttons=False,
                )
                return

            with session_scope() as session:
                decided = approve_admin_request(
                    session,
                    request_id=request_id,
                    admin_max_user_id=max_user_id,
                )
            if not decided:
                await _finish_approval_callback(
                    event, notification="Заявка уже обработана", clear_buttons=True
                )
                return
            notification = "Пользователь добавлен в чат"
            requester_text = (
                f"✅ Администратор одобрил вашу заявку на вступление в чат «{approval.chat_title}»."
            )
        else:
            with session_scope() as session:
                decided = reject_admin_request(
                    session,
                    request_id=request_id,
                    admin_max_user_id=max_user_id,
                )
            if not decided:
                await _finish_approval_callback(
                    event, notification="Заявка уже обработана", clear_buttons=True
                )
                return
            notification = "Заявка отклонена"
            requester_text = (
                f"Администратор отклонил вашу заявку на вступление в чат «{approval.chat_title}»."
            )

        if approval.requester_chat_id is not None:
            try:
                await bot.send_message(chat_id=approval.requester_chat_id, text=requester_text)
            except Exception:
                logger.exception(
                    "Не удалось уведомить пользователя о решении администратора",
                    extra={"request_id": request_id},
                )

        await _finish_approval_callback(event, notification=notification, clear_buttons=True)
