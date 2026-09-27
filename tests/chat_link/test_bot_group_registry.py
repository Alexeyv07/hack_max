"""Реестр групп не меняет привязку адресов; права проверяются через MAX."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from maxapi.enums import ChatType
from maxapi.exceptions.max import MaxApiError
from sqlalchemy import select

from chat_link.api import routes
from chat_link.api.schemas import AdminAddressRequest, AdminGroupRequest
from chat_link.db import BotGroupRow
from chat_link.handlers.registry import (
    deactivate_bot_group,
    eligible_admin_group,
    eligible_admin_groups,
    register_bot_group,
)
from project.database import Base


def _bot(*, user_admin: bool = True, bot_admin: bool = True):
    return SimpleNamespace(
        get_chat_by_id=AsyncMock(return_value=SimpleNamespace(type=ChatType.CHAT, title="Соседи")),
        get_me_from_chat=AsyncMock(
            return_value=SimpleNamespace(
                is_admin=bot_admin, is_owner=False, permissions=["read_all_messages"]
            )
        ),
        get_chat_member=AsyncMock(
            return_value=SimpleNamespace(is_admin=user_admin, is_owner=False)
        ),
        send_message=AsyncMock(),
    )


def test_new_group_registered_without_address_and_deactivated(db_session):
    register_bot_group(db_session, -321, actor_max_user_id=22, title="Наш двор")
    row = db_session.get(BotGroupRow, -321)
    assert row.title == "Наш двор" and row.is_active
    assert row.added_by_user_id == 22
    assert "chat_addresses" in Base.metadata.tables
    register_bot_group(db_session, -321, actor_max_user_id=23, title="Новое название")
    assert row.title == "Новое название" and row.added_by_user_id == 23
    assert db_session.scalars(select(BotGroupRow.chat_id)).all() == [-321]
    deactivate_bot_group(db_session, -321)
    assert row.is_active is False


def test_candidate_requires_both_admins_and_read_all_messages(db_session):
    register_bot_group(db_session, -321, actor_max_user_id=22, title="Наш двор")
    bot = _bot()
    found = asyncio.run(eligible_admin_groups(bot, db_session, max_user_id=22))
    assert [(item.chat_id, item.title) for item in found] == [(-321, "Соседи")]
    assert db_session.get(BotGroupRow, -321).title == "Соседи"
    bot.get_chat_member.return_value.is_admin = False
    assert asyncio.run(eligible_admin_groups(bot, db_session, max_user_id=22)) == []
    bot.get_chat_member.return_value.is_admin = True
    bot.get_me_from_chat.return_value.permissions = []
    assert asyncio.run(eligible_admin_groups(bot, db_session, max_user_id=22)) == []
    bot.get_me_from_chat.return_value.permissions = ["read_all_messages"]
    bot.get_chat_by_id.return_value.type = ChatType.CHANNEL
    assert asyncio.run(eligible_admin_groups(bot, db_session, max_user_id=22)) == []
    deactivate_bot_group(db_session, -321)
    assert asyncio.run(eligible_admin_groups(bot, db_session, max_user_id=22)) == []


def test_missing_membership_is_not_max_outage(db_session):
    register_bot_group(db_session, -321, actor_max_user_id=22)
    bot = _bot()
    bot.get_chat_member.side_effect = MaxApiError(404, {"message": "not found"})
    assert asyncio.run(eligible_admin_group(bot, db_session, chat_id=-321, max_user_id=22)) is None
    bot.get_chat_member.side_effect = MaxApiError(503, {"message": "unavailable"})
    with pytest.raises(MaxApiError) as error:
        asyncio.run(eligible_admin_group(bot, db_session, chat_id=-321, max_user_id=22))
    assert error.value.code == 503


def test_http_checks_and_mirrors_no_candidates(db_session, monkeypatch):
    register_bot_group(db_session, -321, actor_max_user_id=22)
    bot = _bot(user_admin=False)
    monkeypatch.setattr(routes, "get_max_bot", lambda: bot)
    monkeypatch.setattr(
        routes,
        "get_address_catalog",
        lambda: SimpleNamespace(get=lambda id_: SimpleNamespace(id=id_, address_text="Дом 1")),
    )
    response = asyncio.run(
        routes.check_admin_groups(AdminAddressRequest(address_id=22), db_session, 22)
    )
    assert response.items == []
    text = bot.send_message.await_args.kwargs["text"]
    assert "Добавьте бота" in text and "Дом 1" in text
    assert bot.send_message.await_args.kwargs["user_id"] == 22

    bot.get_chat_member.return_value.is_admin = True
    bot.send_message.reset_mock()
    result = asyncio.run(
        routes.check_admin_groups(AdminAddressRequest(address_id=22), db_session, 22)
    )
    assert result.items[0].chat_id == -321
    assert "Чаты, к которым" in bot.send_message.await_args.kwargs["text"]

    confirm = asyncio.run(
        routes.confirm_admin_group(AdminGroupRequest(address_id=22, chat_id=-321), db_session, 22)
    )
    assert confirm.chat_id == -321
    assert "Подтвердите привязку" in bot.send_message.await_args.kwargs["text"]
    assert "Дом 1" in bot.send_message.await_args.kwargs["text"]
    assert (
        bot.send_message.await_args.kwargs["attachments"][0].payload.buttons[0][0].payload
        == "cl:admin:confirm:22:-321"
    )

    bot.get_me_from_chat.side_effect = RuntimeError("MAX unavailable")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.check_admin_groups(AdminAddressRequest(address_id=22), db_session, 22))
    assert exc.value.status_code == 503


def test_swagger_documents_admin_flow_and_keeps_select_schema():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(routes.router)
    paths = app.openapi()["paths"]
    for suffix in ["invitation", "back", "check", "confirm"]:
        endpoint = paths[f"/chat-link/admin/{suffix}"]["post"]
        assert endpoint["summary"] and endpoint["description"]
        assert endpoint["responses"]
    assert paths["/chat-link/select"]["post"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("AddressSelectResponse")


def test_private_callback_after_webapp_works_without_fsm(monkeypatch):
    """Кнопки из ЛС содержат id адреса/чата и работают после закрытия WebApp."""
    from contextlib import contextmanager

    from chat_link.commands import flow
    from chat_link.handlers.registry import AdminGroup

    @contextmanager
    def fake_session_scope():
        yield object()

    class Context:
        def __init__(self):
            self.data = {}

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

    context = Context()
    event = SimpleNamespace(
        callback=SimpleNamespace(user=SimpleNamespace(user_id=22)),
        edit=AsyncMock(),
        ack=AsyncMock(),
    )
    bot = SimpleNamespace(me=SimpleNamespace(username="test_bot"))
    monkeypatch.setattr(flow, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        flow,
        "get_address_catalog",
        lambda: SimpleNamespace(get=lambda id_: SimpleNamespace(id=id_, address_text="Дом 22")),
    )
    monkeypatch.setattr(
        flow,
        "pending_for_address",
        lambda session, *, max_user_id, address_id: SimpleNamespace(token="token"),
    )
    monkeypatch.setattr(
        flow, "eligible_admin_groups", AsyncMock(return_value=[AdminGroup(-321, "Наш двор")])
    )
    monkeypatch.setattr(
        flow, "eligible_admin_group", AsyncMock(return_value=AdminGroup(-321, "Наш двор"))
    )
    monkeypatch.setattr(
        flow,
        "create_start_link",
        lambda username, payload: f"https://max.ru/{username}?start={payload}",
    )

    asyncio.run(flow._show_resident_setup(event, context, bot, address_id=22))
    assert "Дом 22" in event.edit.await_args.kwargs["text"]
    assert (
        event.edit.await_args.kwargs["attachments"][0].payload.buttons[0][0].payload
        == "cl:invite:token:22"
    )

    asyncio.run(flow._show_admin_setup(event, context, bot, address_id=22))
    assert "Чаты, к которым" in event.edit.await_args.kwargs["text"]
    assert (
        event.edit.await_args.kwargs["attachments"][0].payload.buttons[0][0].payload
        == "cl:admin:pick:22:-321"
    )

    asyncio.run(flow._show_admin_confirm(event, context, bot, address_id=22, chat_id=-321))
    assert "Дом 22" in event.edit.await_args.kwargs["text"]
    assert "Наш двор" in event.edit.await_args.kwargs["text"]
    assert (
        event.edit.await_args.kwargs["attachments"][0].payload.buttons[0][0].payload
        == "cl:admin:confirm:22:-321"
    )


def test_swagger_accepts_negative_max_chat_id_for_unlink():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(routes.router)
    endpoint = app.openapi()["paths"]["/chat-link/groups/{chat_id}/addresses/{address_id}"][
        "delete"
    ]
    chat_id = next(item for item in endpoint["parameters"] if item["name"] == "chat_id")
    schema = chat_id["schema"]
    assert schema.get("minimum") is None
    assert -79201841556904 in schema["examples"]
