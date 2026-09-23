"""Уведомления администратору о заявках на вступление в домовой чат."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from address.db.address import AddressRow
from auth.db.user import UserRow
from chat_link.db import ChatLinkRow
from chat_link.models import ChatLinkStatus
from user_chat.db import ChatRow
from user_chat.handlers import add_user_to_chat

ApprovalAction = Literal["approve", "reject"]


@dataclass(frozen=True, slots=True)
class AdminApproval:
    request_id: int
    admin_user_id: int
    admin_max_user_id: int
    admin_chat_id: int
    requester_user_id: int
    requester_max_user_id: int
    requester_chat_id: int | None
    requester_name: str
    chat_id: int
    chat_title: str
    address_text: str


def _select_approval():
    requester = aliased(UserRow, name="approval_requester")
    admin = aliased(UserRow, name="approval_admin")
    return (
        select(ChatLinkRow, requester, admin, ChatRow, AddressRow)
        .join(requester, requester.id == ChatLinkRow.requester_user_id)
        .join(admin, admin.id == ChatLinkRow.admin_user_id)
        .join(ChatRow, ChatRow.chat_id == ChatLinkRow.chat_id)
        .join(AddressRow, AddressRow.id == ChatLinkRow.address_id)
    )


def _domain(row: tuple[ChatLinkRow, UserRow, UserRow, ChatRow, AddressRow]) -> AdminApproval:
    request, requester, admin, chat, address = row
    return AdminApproval(
        request_id=request.id,
        admin_user_id=admin.id,
        admin_max_user_id=admin.max_user_id,
        admin_chat_id=int(admin.chat_id),
        requester_user_id=requester.id,
        requester_max_user_id=requester.max_user_id,
        requester_chat_id=int(requester.chat_id) if requester.chat_id is not None else None,
        requester_name=requester.name or requester.username or "Пользователь MAX",
        chat_id=int(chat.chat_id),
        chat_title=chat.title,
        address_text=address.address_text,
    )


def list_pending_admin_approvals(session: Session) -> list[AdminApproval]:
    """Заявки, по которым администратору ещё не отправляли кнопки решения."""
    admin = aliased(UserRow, name="approval_admin_filter")
    ids = list(
        session.scalars(
            select(ChatLinkRow.id)
            .join(admin, admin.id == ChatLinkRow.admin_user_id)
            .where(
                ChatLinkRow.status == ChatLinkStatus.WAITING_APPROVAL.value,
                ChatLinkRow.chat_id.is_not(None),
                ChatLinkRow.admin_user_id.is_not(None),
                admin.chat_id.is_not(None),
            )
            .order_by(ChatLinkRow.id)
        ).all()
    )
    result: list[AdminApproval] = []
    for request_id in ids:
        row = session.execute(_select_approval().where(ChatLinkRow.id == request_id)).one_or_none()
        if row is not None:
            result.append(_domain(row))
    return result


def get_admin_approval(
    session: Session,
    *,
    request_id: int,
    admin_max_user_id: int,
) -> AdminApproval | None:
    """Получить ещё не решённую заявку только для назначенного администратора."""
    row = session.execute(
        _select_approval().where(
            ChatLinkRow.id == request_id,
            ChatLinkRow.status == ChatLinkStatus.APPROVAL_SENT.value,
        )
    ).one_or_none()
    if row is None:
        return None
    approval = _domain(row)
    if approval.admin_max_user_id != admin_max_user_id:
        return None
    return approval


def mark_approval_notified(session: Session, *, request_id: int) -> bool:
    row = session.get(ChatLinkRow, request_id)
    if row is None or row.status != ChatLinkStatus.WAITING_APPROVAL.value:
        return False
    row.status = ChatLinkStatus.APPROVAL_SENT.value
    session.flush()
    return True


def approve_admin_request(
    session: Session,
    *,
    request_id: int,
    admin_max_user_id: int,
) -> bool:
    """Завершить уже подтверждённое через MAX добавление пользователя."""
    approval = get_admin_approval(
        session,
        request_id=request_id,
        admin_max_user_id=admin_max_user_id,
    )
    if approval is None:
        return False
    add_user_to_chat(
        session,
        approval.chat_id,
        max_user_id=approval.requester_max_user_id,
    )
    row = session.get(ChatLinkRow, request_id)
    row.status = ChatLinkStatus.CONNECTED.value
    session.flush()
    return True


def reject_admin_request(
    session: Session,
    *,
    request_id: int,
    admin_max_user_id: int,
) -> bool:
    approval = get_admin_approval(
        session,
        request_id=request_id,
        admin_max_user_id=admin_max_user_id,
    )
    if approval is None:
        return False
    row = session.get(ChatLinkRow, request_id)
    row.status = ChatLinkStatus.REJECTED.value
    session.flush()
    return True


def build_admin_approval_text(approval: AdminApproval) -> str:
    return (
        "Новая заявка на вступление в домовой чат\n\n"
        f"Чат: {approval.chat_title}\n"
        f"Адрес: {approval.address_text}\n"
        f"Пользователь: {approval.requester_name}\n\n"
        "Добавить пользователя в чат?"
    )


def approval_payload(request_id: int, action: ApprovalAction) -> str:
    return f"notify:approval:{action}:{request_id}"


def parse_approval_payload(payload: str) -> tuple[ApprovalAction, int] | None:
    parts = payload.split(":")
    if len(parts) != 4 or parts[:2] != ["notify", "approval"]:
        return None
    action = parts[2]
    if action not in {"approve", "reject"} or not parts[3].isdigit():
        return None
    request_id = int(parts[3])
    if request_id <= 0:
        return None
    return action, request_id
