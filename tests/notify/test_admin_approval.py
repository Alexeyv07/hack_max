from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from address.db import AddressRow
from auth.db import UserRow
from chat_link.db import ChatLinkRow
from chat_link.handlers import create_request, request_admin_approval
from chat_link.models import ChatLinkStatus
from notify.admin_approval import (
    approve_admin_request,
    get_admin_approval,
    parse_approval_payload,
    reject_admin_request,
)
from notify.worker import run_admin_approval_cycle
from user_chat.db import ChatRow
from user_chat.handlers import list_chat_members


def _seed_flow(session):
    address = AddressRow(
        address_text="Москва, Тестовая улица, д. 1",
        city="Москва",
        district="Тестовый район",
        street="Тестовая улица",
        house="1",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
    )
    admin = UserRow(max_user_id=1001, name="Админ", chat_id=5001)
    requester = UserRow(max_user_id=1002, name="Сосед", chat_id=5002)
    session.add_all([address, admin, requester])
    session.flush()

    chat = ChatRow(
        chat_id=-7001,
        address_id=address.id,
        title="Домовой чат",
        chat_type="chat",
    )
    session.add(chat)
    session.flush()

    session.add(
        ChatLinkRow(
            token="setup-token",
            requester_user_id=admin.id,
            admin_user_id=admin.id,
            address_id=address.id,
            chat_id=chat.chat_id,
            status=ChatLinkStatus.CONNECTED.value,
        )
    )
    session.flush()

    request, chats = create_request(
        session,
        max_user_id=requester.max_user_id,
        address_id=address.id,
    )
    assert [item.chat_id for item in chats] == [chat.chat_id]
    request_admin_approval(session, token=request.token, chat_id=chat.chat_id)
    session.flush()
    return admin, requester, chat, request


def test_existing_chat_request_becomes_admin_approval(db_session) -> None:
    admin, requester, chat, request = _seed_flow(db_session)

    row = db_session.get(ChatLinkRow, request.id)
    assert row.status == ChatLinkStatus.WAITING_APPROVAL.value
    assert row.chat_id == chat.chat_id
    assert row.admin_user_id == admin.id
    assert list_chat_members(db_session, chat.chat_id) == []
    assert requester.id != admin.id


def test_admin_approval_notification_is_sent_once(session_factory) -> None:
    with session_factory() as session:
        _admin, _requester, _chat, request = _seed_flow(session)
        session.commit()

    bot = SimpleNamespace(send_message=AsyncMock())

    assert (
        asyncio.run(
            run_admin_approval_cycle(
                bot,
                session_factory=session_factory,
                keyboard_factory=lambda approval: f"approval:{approval.request_id}",
            )
        )
        == 1
    )
    assert asyncio.run(run_admin_approval_cycle(bot, session_factory=session_factory)) == 0

    first = bot.send_message.await_args_list[0].kwargs
    assert first["chat_id"] == 5001
    assert "Сосед" in first["text"]
    assert "Домовой чат" in first["text"]
    assert first["attachments"] == [f"approval:{request.id}"]

    with session_factory() as session:
        row = session.get(ChatLinkRow, request.id)
        assert row.status == ChatLinkStatus.APPROVAL_SENT.value


def test_admin_approve_connects_requester(db_session) -> None:
    admin, requester, chat, request = _seed_flow(db_session)
    row = db_session.get(ChatLinkRow, request.id)
    row.status = ChatLinkStatus.APPROVAL_SENT.value
    db_session.flush()

    approval = get_admin_approval(
        db_session,
        request_id=request.id,
        admin_max_user_id=admin.max_user_id,
    )
    assert approval is not None
    assert approval.requester_max_user_id == requester.max_user_id

    assert approve_admin_request(
        db_session,
        request_id=request.id,
        admin_max_user_id=admin.max_user_id,
    )
    assert db_session.get(ChatLinkRow, request.id).status == ChatLinkStatus.CONNECTED.value
    assert [member.max_user_id for member in list_chat_members(db_session, chat.chat_id)] == [
        requester.max_user_id
    ]


def test_admin_reject_keeps_requester_outside_chat(db_session) -> None:
    admin, requester, chat, request = _seed_flow(db_session)
    row = db_session.get(ChatLinkRow, request.id)
    row.status = ChatLinkStatus.APPROVAL_SENT.value
    db_session.flush()

    assert reject_admin_request(
        db_session,
        request_id=request.id,
        admin_max_user_id=admin.max_user_id,
    )
    assert db_session.get(ChatLinkRow, request.id).status == ChatLinkStatus.REJECTED.value
    assert list_chat_members(db_session, chat.chat_id) == []
    assert requester.max_user_id == 1002


def test_approval_payload_is_strict() -> None:
    assert parse_approval_payload("notify:approval:approve:15") == ("approve", 15)
    assert parse_approval_payload("notify:approval:reject:16") == ("reject", 16)
    assert parse_approval_payload("notify:approval:approve:0") is None
    assert parse_approval_payload("notify:approval:maybe:15") is None
    assert parse_approval_payload("notify:ack:15") is None
