"""Уже подключённый дом: доступ только после проверки реального членства в MAX."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from address.db import AddressRow
from auth.db import UserRow
from chat_link.api import routes
from chat_link.api.schemas import AddressSelectRequest, ChatLinkNavigationRequest
from chat_link.db import ChatLinkRow
from chat_link.models import ChatLinkStatus
from user_chat.db import ChatRow, chat_addresses
from user_chat.handlers import (
    add_chat_address,
    add_user_to_chat,
    list_chat_members,
    list_memberships_for_user,
)


def _seed(session):
    address = AddressRow(
        address_text="Москва, Тестовая улица, д. 1",
        city="Москва",
        district="Тестовый район",
        street="Тестовая улица",
        house="1",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
    )
    admin = UserRow(max_user_id=1001, name="Администратор", chat_id=5001)
    resident = UserRow(max_user_id=1002, name="Житель", chat_id=5002)
    session.add_all([address, admin, resident])
    session.flush()
    chat = ChatRow(chat_id=-7001, address_id=address.id, title="Домовой чат", chat_type="chat")
    session.add(chat)
    session.flush()
    session.execute(chat_addresses.insert().values(chat_id=chat.chat_id, address_id=address.id))
    session.add(
        ChatLinkRow(
            token="old-setup-token",
            requester_user_id=admin.id,
            admin_user_id=admin.id,
            address_id=address.id,
            chat_id=chat.chat_id,
            status=ChatLinkStatus.CONNECTED.value,
        )
    )
    session.flush()
    return address, admin, resident, chat


def _configure(monkeypatch, session, bot):
    monkeypatch.setattr(
        routes,
        "get_address_catalog",
        lambda: SimpleNamespace(get=lambda address_id: session.get(AddressRow, address_id)),
    )
    monkeypatch.setattr(routes, "get_max_bot", lambda: bot)


def _select(session, address_id, max_user_id, *, resident_chat_id=None):
    return asyncio.run(
        routes.select_address(
            AddressSelectRequest(address_id=address_id, resident_chat_id=resident_chat_id),
            session,
            max_user_id,
        )
    )


@pytest.mark.parametrize("is_admin", [False, True])
def test_existing_member_or_admin_binds_without_request(db_session, monkeypatch, is_admin):
    address, admin, resident, chat = _seed(db_session)
    actor = admin if is_admin else resident
    lookup = AsyncMock(return_value=SimpleNamespace(is_admin=is_admin, is_owner=False))
    _configure(monkeypatch, db_session, SimpleNamespace(get_chat_member=lookup))
    before = db_session.scalars(select(ChatLinkRow.id)).all()

    result = _select(db_session, address.id, actor.max_user_id, resident_chat_id=chat.chat_id)

    assert result.mode == "resident_address"
    assert result.token is None and result.admin_link is None and result.chats == []
    assert db_session.scalars(select(ChatLinkRow.id)).all() == before
    assert actor.max_user_id in [
        member.max_user_id for member in list_chat_members(db_session, chat.chat_id)
    ]
    lookup.assert_awaited_once_with(chat.chat_id, actor.max_user_id)


def test_non_member_is_denied_without_new_request_or_invite(db_session, monkeypatch):
    address, _admin, resident, chat = _seed(db_session)
    lookup = AsyncMock(return_value=None)
    _configure(monkeypatch, db_session, SimpleNamespace(get_chat_member=lookup))
    before = db_session.scalars(select(ChatLinkRow.id)).all()

    with pytest.raises(HTTPException) as exc:
        _select(db_session, address.id, resident.max_user_id, resident_chat_id=chat.chat_id)

    assert exc.value.status_code == 403
    assert "вступите" in exc.value.detail
    assert db_session.scalars(select(ChatLinkRow.id)).all() == before
    assert list_chat_members(db_session, chat.chat_id) == []
    lookup.assert_awaited_once_with(chat.chat_id, resident.max_user_id)


def test_max_unavailable_or_failed_fails_closed(db_session, monkeypatch):
    address, _admin, resident, chat = _seed(db_session)
    _configure(monkeypatch, db_session, None)
    with pytest.raises(HTTPException) as missing:
        _select(db_session, address.id, resident.max_user_id, resident_chat_id=chat.chat_id)
    assert missing.value.status_code == 503

    lookup = AsyncMock(side_effect=RuntimeError("MAX unavailable"))
    _configure(monkeypatch, db_session, SimpleNamespace(get_chat_member=lookup))
    with pytest.raises(HTTPException) as failed:
        _select(db_session, address.id, resident.max_user_id, resident_chat_id=chat.chat_id)
    assert failed.value.status_code == 503
    assert list_chat_members(db_session, chat.chat_id) == []


def test_explicit_group_binds_only_selected_verified_member(db_session, monkeypatch):
    address, _admin, resident, chat = _seed(db_session)
    other = ChatRow(chat_id=-7002, address_id=address.id, title="Другой чат", chat_type="chat")
    db_session.add(other)
    db_session.flush()
    db_session.execute(chat_addresses.insert().values(chat_id=other.chat_id, address_id=address.id))
    lookup = AsyncMock(
        side_effect=lambda chat_id, user_id: (
            SimpleNamespace(is_admin=False) if chat_id == other.chat_id else None
        )
    )
    _configure(monkeypatch, db_session, SimpleNamespace(get_chat_member=lookup))

    result = _select(db_session, address.id, resident.max_user_id, resident_chat_id=other.chat_id)

    assert result.mode == "resident_address"
    assert list_chat_members(db_session, chat.chat_id) == []
    assert [m.max_user_id for m in list_chat_members(db_session, other.chat_id)] == [
        resident.max_user_id
    ]
    lookup.assert_awaited_once_with(other.chat_id, resident.max_user_id)


def test_plain_selection_checks_selected_address_chat(db_session, monkeypatch):
    address, _admin, resident, chat = _seed(db_session)
    another = AddressRow(
        address_text="Москва, Без чата, д. 2",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
    )
    db_session.add(another)
    db_session.flush()
    lookup = AsyncMock(return_value=SimpleNamespace(is_admin=False))
    _configure(
        monkeypatch,
        db_session,
        SimpleNamespace(
            get_chat_member=lookup,
            me=SimpleNamespace(username="smart_city_bot"),
            send_message=AsyncMock(),
        ),
    )

    # Даже посторонний вправе выбрать адрес, а MAX подтверждает членство.
    selected = _select(db_session, address.id, resident.max_user_id)
    assert selected.mode == "personal_address"
    assert db_session.get(UserRow, resident.id).address_id == address.id
    lookup.assert_awaited_once_with(chat.chat_id, resident.max_user_id)

    # Другой адрес без подключённого чата не открывает персональную ленту.
    other = _select(db_session, another.id, resident.max_user_id)
    assert other.mode == "no_chat" and other.token and other.admin_link
    assert db_session.get(UserRow, resident.id).address_id == address.id
    lookup.assert_awaited_once()


def test_plain_selection_shows_join_advice_for_non_member(db_session, monkeypatch):
    address, _admin, resident, chat = _seed(db_session)
    add_user_to_chat(db_session, chat.chat_id, max_user_id=resident.max_user_id)
    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=None), send_message=AsyncMock())
    _configure(monkeypatch, db_session, bot)
    result = _select(db_session, address.id, resident.max_user_id)
    assert result.mode == "not_member"
    assert db_session.get(UserRow, resident.id).address_id is None
    assert list_chat_members(db_session, chat.chat_id) == []
    assert "Госуслуги Дом" in bot.send_message.await_args.kwargs["text"]
    buttons = bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
    assert [row[0].text for row in buttons] == ["Проверить еще раз", "Назад"]
    assert buttons[0][0].payload == f"cl:residence:retry:{address.id}"
    bot.get_chat_member.assert_awaited_once_with(chat.chat_id, resident.max_user_id)


def test_webapp_retry_checks_max_again_and_mirrors_both_screens(db_session, monkeypatch):
    address, _admin, resident, chat = _seed(db_session)
    lookup = AsyncMock(side_effect=[None, SimpleNamespace(is_admin=False)])
    bot = SimpleNamespace(get_chat_member=lookup, send_message=AsyncMock())
    _configure(monkeypatch, db_session, bot)
    payload = AddressSelectRequest(
        address_id=address.id, resident_chat_id=chat.chat_id, onboarding=True
    )

    waiting = asyncio.run(routes.select_address(payload, db_session, resident.max_user_id))
    assert waiting.mode == "not_member"
    assert db_session.get(UserRow, resident.id).address_id is None
    wait_message = bot.send_message.await_args.kwargs
    assert "Госуслуги Дом" in wait_message["text"]
    assert [row[0].text for row in wait_message["attachments"][0].payload.buttons] == [
        "Проверить еще раз",
        "Назад",
    ]
    assert (
        wait_message["attachments"][0].payload.buttons[0][0].payload
        == f"cl:residence:retry:{address.id}:{chat.chat_id}"
    )

    success = asyncio.run(routes.select_address(payload, db_session, resident.max_user_id))
    assert success.mode == "resident_address"
    assert db_session.get(UserRow, resident.id).address_id == address.id
    success_message = bot.send_message.await_args.kwargs
    assert "Чат успешно добавлен" in success_message["text"]
    assert success_message["attachments"][0].payload.buttons[0][0].text == "На главную"
    assert success_message["attachments"][0].payload.buttons[0][0].payload == "home:addresses:home"
    assert lookup.await_count == 2


def test_webapp_does_not_offer_join_for_address_not_linked_to_target_chat(db_session, monkeypatch):
    _address, _admin, resident, chat = _seed(db_session)
    foreign = AddressRow(
        address_text="Москва, Другой дом, д. 7",
        latitude=Decimal("55.7503000"),
        longitude=Decimal("37.6103000"),
    )
    db_session.add(foreign)
    db_session.flush()
    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=None), send_message=AsyncMock())
    _configure(monkeypatch, db_session, bot)

    with pytest.raises(HTTPException) as error:
        _select(db_session, foreign.id, resident.max_user_id, resident_chat_id=chat.chat_id)
    assert error.value.status_code == 403  # старый контракт без onboarding

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            routes.select_address(
                AddressSelectRequest(
                    address_id=foreign.id, resident_chat_id=chat.chat_id, onboarding=True
                ),
                db_session,
                resident.max_user_id,
            )
        )
    assert error.value.status_code == 409
    bot.send_message.assert_not_awaited()


def test_webapp_navigation_mirrors_home_and_picker(db_session, monkeypatch):
    _address, _admin, resident, _chat = _seed(db_session)
    bot = SimpleNamespace(send_message=AsyncMock(), me=SimpleNamespace(username="test_bot"))
    _configure(monkeypatch, db_session, bot)
    home = AsyncMock()
    monkeypatch.setattr(routes, "send_home", home)

    response = asyncio.run(
        routes.navigate_chat_link(
            ChatLinkNavigationRequest(action="choose_address"), db_session, resident.max_user_id
        )
    )
    assert response.status_code == 204
    assert "Выберите удобный способ" in bot.send_message.await_args.kwargs["text"]
    attachments = bot.send_message.await_args.kwargs["attachments"]
    assert attachments[0].path.endswith("other_messages.webp")
    assert attachments[1].payload.buttons[0][0].text == "Выбрать адрес"

    response = asyncio.run(
        routes.navigate_chat_link(
            ChatLinkNavigationRequest(action="home"), db_session, resident.max_user_id
        )
    )
    assert response.status_code == 204
    home.assert_awaited_once_with(bot, db_session, resident.max_user_id)


def test_navigation_is_documented_without_removing_select_contract():
    from events.api.app import create_app

    spec = create_app().openapi()
    assert "post" in spec["paths"]["/chat-link/navigation"]
    assert "post" in spec["paths"]["/chat-link/select"]
    request = spec["components"]["schemas"]["AddressSelectRequest"]
    assert request["properties"]["onboarding"]["default"] is False
    assert "mode" in spec["components"]["schemas"]["AddressSelectResponse"]["properties"]
    onboarding_request = {"address_id": 881, "resident_chat_id": 123456789, "onboarding": True}
    assert onboarding_request in request["examples"]
    response_examples = spec["components"]["schemas"]["AddressSelectResponse"]["examples"]
    assert {item["mode"] for item in response_examples} >= {"resident_address", "not_member"}

    navigation = spec["paths"]["/chat-link/navigation"]["post"]
    assert navigation["responses"]["204"]["description"]
    assert "content" not in navigation["responses"]["204"]
    navigation_examples = spec["components"]["schemas"]["ChatLinkNavigationRequest"]["examples"]
    assert navigation_examples == [{"action": "home"}, {"action": "choose_address"}]


def test_migration_closes_old_admin_approvals(db_session):
    """Эквивалент SQL-миграции 0018_membership_only без alembic."""
    address, admin, resident, chat = _seed(db_session)
    for token, state in (
        ("old-pending", ChatLinkStatus.WAITING_APPROVAL),
        ("old-sent", ChatLinkStatus.APPROVAL_SENT),
    ):
        db_session.add(
            ChatLinkRow(
                token=token,
                requester_user_id=resident.id,
                admin_user_id=admin.id,
                address_id=address.id,
                chat_id=chat.chat_id,
                status=state.value,
            )
        )
    db_session.flush()

    up_sql = (
        Path(__file__).resolve().parents[2] / "db/migrations/0018_membership_only.up.sql"
    ).read_text(encoding="utf-8")
    for statement in (s.strip() for s in up_sql.split(";") if s.strip()):
        db_session.execute(text(statement))
    db_session.commit()
    db_session.expire_all()

    statuses = dict(db_session.execute(select(ChatLinkRow.token, ChatLinkRow.status)).all())
    assert statuses["old-pending"] == ChatLinkStatus.CANCELLED.value
    assert statuses["old-sent"] == ChatLinkStatus.CANCELLED.value
    assert statuses["old-setup-token"] == ChatLinkStatus.CONNECTED.value


def test_referral_resident_selects_only_group_addresses(db_session, monkeypatch):
    first, _admin, resident, chat = _seed(db_session)
    second = AddressRow(
        address_text="Москва, Тестовая улица, д. 2",
        latitude=Decimal("55.7502000"),
        longitude=Decimal("37.6102000"),
    )
    foreign = AddressRow(
        address_text="Москва, Другая улица, д. 3",
        latitude=Decimal("55.8000000"),
        longitude=Decimal("37.6500000"),
    )
    db_session.add_all([second, foreign])
    db_session.flush()
    add_chat_address(db_session, chat.chat_id, second.id)
    lookup = AsyncMock(return_value=SimpleNamespace(is_admin=False))
    _configure(monkeypatch, db_session, SimpleNamespace(get_chat_member=lookup))

    bad = AddressSelectRequest(address_id=foreign.id, resident_chat_id=chat.chat_id)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.select_address(bad, db_session, resident.max_user_id))
    assert error.value.status_code == 409
    assert list_memberships_for_user(db_session, resident.max_user_id) == []

    good = AddressSelectRequest(address_id=second.id, resident_chat_id=chat.chat_id)
    result = asyncio.run(routes.select_address(good, db_session, resident.max_user_id))
    assert result.mode == "resident_address"
    assert list_memberships_for_user(db_session, resident.max_user_id)[0].address_id == second.id
    assert first.id != second.id
