from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from address.db.address import AddressRow
from auth.db.user import UserRow
from events.db.event import EventRow
from notify.db import NotifyCursorRow, NotifyDeliveryRow, NotifyDigestRow
from user_chat.db import ChatRow


def _seed_dependencies(db_session):
    address = AddressRow(
        address_text="Москва, Тестовая улица, д. 1",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6200000"),
    )
    user = UserRow(max_user_id=1001, name="Тест")
    event = EventRow(
        title="Отключение воды",
        body="До 18:00",
        importance=2,
        source="news",
        address=address,
        weight=0.8,
    )
    chat = ChatRow(
        chat_id=-5001,
        title="Домовой чат",
        address=address,
        chat_type="chat",
    )
    db_session.add_all([address, user, event, chat])
    db_session.flush()
    return user, event, chat


def test_notify_state_rows_are_persisted(db_session) -> None:
    user, event, chat = _seed_dependencies(db_session)

    delivery = NotifyDeliveryRow(user_id=user.id, event_id=event.id)
    digest = NotifyDigestRow(chat_id=chat.chat_id)
    cursor = NotifyCursorRow(name="priority", last_event_id=event.id)
    db_session.add_all([delivery, digest, cursor])
    db_session.flush()

    assert delivery.attempts == 0
    assert delivery.acked_at is None
    assert digest.last_digest_date is None
    assert digest.last_message_at is None
    assert cursor.last_event_id == event.id


def test_delivery_is_unique_per_user_and_event(db_session) -> None:
    user, event, _chat = _seed_dependencies(db_session)
    db_session.add(NotifyDeliveryRow(user_id=user.id, event_id=event.id))
    db_session.flush()

    db_session.add(NotifyDeliveryRow(user_id=user.id, event_id=event.id))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
