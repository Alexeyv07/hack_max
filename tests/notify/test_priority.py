from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import auth.commands.start as start
import notify.commands as commands
from address.db.address import AddressRow
from auth.db.user import UserRow
from events.db.event import EventRow
from notify.commands import _finish_ack_callback
from notify.db import NotifyCursorRow, NotifyDeliveryRow
from notify.priority import (
    PRIORITY_CURSOR,
    acknowledge_delivery,
    enqueue_new_priority_deliveries,
    parse_ack_payload,
)
from notify.worker import run_priority_cycle
from project.config import NotifyConfig
from user_chat.db import ChatRow, users_chat


def _address(text: str, *, city: str, street: str, house: str) -> AddressRow:
    return AddressRow(
        address_text=text,
        city=city,
        street=street,
        house=house,
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6200000"),
    )


def _seed_member(
    session, *, max_user_id: int, private_chat_id: int, address: AddressRow
) -> UserRow:
    user = UserRow(max_user_id=max_user_id, name=f"User {max_user_id}", chat_id=private_chat_id)
    chat = ChatRow(
        chat_id=-(max_user_id + 10000),
        title="Домовой чат",
        address=address,
        chat_type="chat",
    )
    session.add_all([user, chat])
    session.flush()
    session.execute(users_chat.insert().values(user_id=user.id, chat_id=chat.chat_id))
    return user


def _event(
    *,
    address: AddressRow,
    title: str,
    importance: int,
    geo_by: str = "home",
) -> EventRow:
    return EventRow(
        title=title,
        body=f"Подробности: {title}",
        importance=importance,
        source="news",
        address=address,
        geo_by=geo_by,
        weight=0.9,
    )


def _enable_cursor(session) -> None:
    session.add(NotifyCursorRow(name=PRIORITY_CURSOR, last_event_id=0))
    session.flush()


def test_priority_scale_enqueues_importance_1_and_2_but_not_3(db_session) -> None:
    address = _address("Москва, Тестовая улица, д. 1", city="Москва", street="Тестовая", house="1")
    db_session.add(address)
    db_session.flush()
    user = _seed_member(db_session, max_user_id=1001, private_chat_id=5001, address=address)
    _enable_cursor(db_session)
    first = _event(address=address, title="Критичное", importance=1)
    second = _event(address=address, title="Важное", importance=2)
    noise = _event(address=address, title="Шум", importance=3)
    db_session.add_all([first, second, noise])
    db_session.flush()

    created = enqueue_new_priority_deliveries(db_session)

    deliveries = list(db_session.query(NotifyDeliveryRow).order_by(NotifyDeliveryRow.event_id))
    assert created == 2
    assert [(row.user_id, row.event_id) for row in deliveries] == [
        (user.id, first.id),
        (user.id, second.id),
    ]
    cursor = db_session.get(NotifyCursorRow, PRIORITY_CURSOR)
    assert cursor is not None
    assert cursor.last_event_id == noise.id


def test_priority_geo_scope_uses_confirmed_chat_memberships(db_session) -> None:
    home = _address("Москва, Первая улица, д. 1", city="Москва", street="Первая улица", house="1")
    same_street = _address(
        "Москва, Первая улица, д. 2", city="Москва", street="Первая улица", house="2"
    )
    other_street = _address(
        "Москва, Вторая улица, д. 3", city="Москва", street="Вторая улица", house="3"
    )
    other_city = _address(
        "Химки, Первая улица, д. 4", city="Химки", street="Первая улица", house="4"
    )
    db_session.add_all([home, same_street, other_street, other_city])
    db_session.flush()
    user_home = _seed_member(db_session, max_user_id=1101, private_chat_id=5101, address=home)
    user_street = _seed_member(
        db_session, max_user_id=1102, private_chat_id=5102, address=same_street
    )
    user_city = _seed_member(
        db_session, max_user_id=1103, private_chat_id=5103, address=other_street
    )
    _seed_member(db_session, max_user_id=1104, private_chat_id=5104, address=other_city)
    _enable_cursor(db_session)

    db_session.add(_event(address=home, title="Улица", importance=2, geo_by="street"))
    db_session.flush()
    enqueue_new_priority_deliveries(db_session)

    recipient_ids = set(db_session.scalars(db_session.query(NotifyDeliveryRow.user_id).statement))
    assert recipient_ids == {user_home.id, user_street.id}

    cursor = db_session.get(NotifyCursorRow, PRIORITY_CURSOR)
    assert cursor is not None
    city_event = _event(address=home, title="Город", importance=2, geo_by="city")
    db_session.add(city_event)
    db_session.flush()
    enqueue_new_priority_deliveries(db_session)

    city_recipient_ids = set(
        db_session.scalars(
            db_session.query(NotifyDeliveryRow.user_id)
            .filter(NotifyDeliveryRow.event_id == city_event.id)
            .statement
        )
    )
    assert city_recipient_ids == {user_home.id, user_street.id, user_city.id}


def test_first_cursor_initialization_does_not_backfill_old_events(db_session) -> None:
    address = _address("Москва, Тестовая улица, д. 1", city="Москва", street="Тестовая", house="1")
    db_session.add(address)
    db_session.flush()
    _seed_member(db_session, max_user_id=1201, private_chat_id=5201, address=address)
    event = _event(address=address, title="Уже было", importance=1)
    db_session.add(event)
    db_session.flush()

    assert enqueue_new_priority_deliveries(db_session) == 0
    assert db_session.query(NotifyDeliveryRow).count() == 0
    cursor = db_session.get(NotifyCursorRow, PRIORITY_CURSOR)
    assert cursor is not None
    assert cursor.last_event_id == event.id


def test_priority_cycle_retries_after_interval_and_ack_stops_it(session_factory) -> None:
    cfg = NotifyConfig(retry_interval_seconds=3600)
    first_send = datetime(2026, 9, 21, 12, tzinfo=UTC)

    with session_factory() as session:
        address = _address(
            "Москва, Тестовая улица, д. 1", city="Москва", street="Тестовая", house="1"
        )
        session.add(address)
        session.flush()
        user = _seed_member(session, max_user_id=1301, private_chat_id=5301, address=address)
        _enable_cursor(session)
        event = _event(address=address, title="Отключение воды", importance=1)
        session.add(event)
        session.commit()

    bot = SimpleNamespace(send_message=AsyncMock())

    def keyboard_factory(delivery):
        return f"ack:{delivery.delivery_id}"

    assert (
        asyncio.run(
            run_priority_cycle(
                bot,
                now=first_send,
                config=cfg,
                session_factory=session_factory,
                keyboard_factory=keyboard_factory,
            )
        )
        == 1
    )
    assert (
        asyncio.run(
            run_priority_cycle(
                bot,
                now=first_send + timedelta(minutes=59),
                config=cfg,
                session_factory=session_factory,
                keyboard_factory=keyboard_factory,
            )
        )
        == 0
    )
    assert (
        asyncio.run(
            run_priority_cycle(
                bot,
                now=first_send + timedelta(hours=1),
                config=cfg,
                session_factory=session_factory,
                keyboard_factory=keyboard_factory,
            )
        )
        == 1
    )

    with session_factory() as session:
        delivery = session.query(NotifyDeliveryRow).one()
        assert delivery.user_id == user.id
        assert delivery.attempts == 2
        assert delivery.first_sent_at is not None
        assert delivery.last_sent_at is not None
        assert acknowledge_delivery(
            session,
            delivery_id=delivery.id,
            max_user_id=1301,
            acked_at=first_send + timedelta(hours=1, minutes=1),
        )
        session.commit()

    assert (
        asyncio.run(
            run_priority_cycle(
                bot,
                now=first_send + timedelta(hours=2, minutes=1),
                config=cfg,
                session_factory=session_factory,
                keyboard_factory=keyboard_factory,
            )
        )
        == 0
    )
    assert bot.send_message.await_count == 2
    first_call = bot.send_message.await_args_list[0].kwargs
    assert first_call["chat_id"] == 5301
    assert "Отключение воды" in first_call["text"]
    assert first_call["attachments"][0].startswith("ack:")


def test_ack_requires_delivery_owner_and_payload_is_strict(db_session) -> None:
    address = _address("Москва, Тестовая улица, д. 1", city="Москва", street="Тестовая", house="1")
    db_session.add(address)
    db_session.flush()
    user = _seed_member(db_session, max_user_id=1401, private_chat_id=5401, address=address)
    event = _event(address=address, title="Важное", importance=2)
    db_session.add(event)
    db_session.flush()
    delivery = NotifyDeliveryRow(user_id=user.id, event_id=event.id)
    db_session.add(delivery)
    db_session.flush()

    assert not acknowledge_delivery(db_session, delivery_id=delivery.id, max_user_id=9999)
    assert delivery.acked_at is None
    assert acknowledge_delivery(db_session, delivery_id=delivery.id, max_user_id=1401)
    assert delivery.acked_at is not None
    assert parse_ack_payload(f"notify:ack:{delivery.id}") == delivery.id
    assert parse_ack_payload("notify:ack:0") is None
    assert parse_ack_payload("notify:ack:nope") is None
    assert parse_ack_payload("cl:noop") is None


def test_ack_callback_gives_visual_confirmation() -> None:
    event = SimpleNamespace(edit=AsyncMock(), ack=AsyncMock())

    asyncio.run(_finish_ack_callback(event, acknowledged=True))

    event.edit.assert_awaited_once_with(
        attachments=[],
        notification="Отмечено как увиденное",
        notify=False,
    )
    event.ack.assert_not_awaited()


def test_ack_callback_falls_back_to_plain_ack_if_edit_fails() -> None:
    event = SimpleNamespace(
        edit=AsyncMock(side_effect=RuntimeError("edit failed")),
        ack=AsyncMock(),
    )

    asyncio.run(_finish_ack_callback(event, acknowledged=True))

    event.ack.assert_awaited_once_with(notification="Отмечено как увиденное")


class _CallbackDispatcher:
    def __init__(self) -> None:
        self.handlers = []

    def message_callback(self, _filter):
        def register(handler):
            self.handlers.append(handler)
            return handler

        return register


def test_ack_opens_fresh_main_menu_only_once_for_owner(session_factory, monkeypatch) -> None:
    with session_factory() as session:
        address = _address(
            "Москва, Тестовая улица, д. 1", city="Москва", street="Тестовая", house="1"
        )
        session.add(address)
        session.flush()
        _seed_member(session, max_user_id=1501, private_chat_id=5501, address=address)
        event = _event(address=address, title="Важное", importance=2)
        session.add(event)
        session.flush()
        user = session.query(UserRow).filter_by(max_user_id=1501).one()
        delivery = NotifyDeliveryRow(user_id=user.id, event_id=event.id)
        session.add(delivery)
        session.commit()
        delivery_id = delivery.id

    @contextmanager
    def scoped_session():
        with session_factory() as session:
            yield session
            session.commit()

    monkeypatch.setattr(commands, "session_scope", scoped_session)
    render_welcome = AsyncMock()
    monkeypatch.setattr(start, "_render_welcome", render_welcome)
    dp = _CallbackDispatcher()
    bot = SimpleNamespace()
    commands.register_notify_commands(dp, bot)
    handler = dp.handlers[0]
    context = SimpleNamespace()

    def callback(user_id):
        return SimpleNamespace(
            callback=SimpleNamespace(
                payload=f"notify:ack:{delivery_id}",
                user=SimpleNamespace(user_id=user_id),
            ),
            edit=AsyncMock(),
            ack=AsyncMock(),
        )

    other = callback(9999)
    asyncio.run(handler(other, context))
    other.edit.assert_not_awaited()
    render_welcome.assert_not_awaited()

    first = callback(1501)
    asyncio.run(handler(first, context))
    first.edit.assert_awaited_once()
    render_welcome.assert_awaited_once()
    args, kwargs = render_welcome.await_args
    assert args[0] is bot
    assert args[1] is first
    assert args[2] is context
    assert args[3].max_user_id == 1501
    assert kwargs == {"recipient_chat_id": 5501}

    repeated = callback(1501)
    asyncio.run(handler(repeated, context))
    repeated.edit.assert_awaited_once()
    render_welcome.assert_awaited_once()

    with session_factory() as session:
        assert session.get(NotifyDeliveryRow, delivery_id).acked_at is not None
