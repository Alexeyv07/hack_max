"""Тесты handlers: CRUD in-process + feed/map."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from address.db.address import AddressRow
from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload
from events.handlers import crud
from events.models.event import EventCreate, EventSource, EventUpdate
from user_chat.handlers import add_user_to_chat, create_chat
from user_chat.models import ChatCreate


def add_address(
    db_session,
    *,
    lat: float,
    lon: float,
    suffix: str,
    street: str | None = "Тестовая",
) -> AddressRow:
    row = AddressRow(
        address_text=f"Москва, улица Тестовая, д. {suffix}",
        postal_code="123456",
        street=street,
        house=suffix,
        latitude=Decimal(str(lat)),
        longitude=Decimal(str(lon)),
    )
    db_session.add(row)
    db_session.flush()
    return row


def seed_user_chat(
    db_session,
    *,
    max_user_id: int,
    chat_id: int,
    lat: float,
    lon: float,
    street: str = "Тестовая",
) -> AddressRow:
    authorize_user(
        db_session,
        MaxUserPayload(max_user_id=max_user_id, name="U", username=f"u{max_user_id}"),
    )
    address = add_address(
        db_session,
        lat=lat,
        lon=lon,
        suffix=f"home-{chat_id}",
        street=street,
    )
    create_chat(db_session, ChatCreate(chat_id=chat_id, address_id=address.id))
    add_user_to_chat(db_session, chat_id, max_user_id=max_user_id)
    return address


def test_create_get_update_delete(db_session) -> None:
    first_address = add_address(db_session, lat=55.75, lon=37.62, suffix="1")
    second_address = add_address(db_session, lat=55.751, lon=37.621, suffix="2")

    created = crud.create_event(
        db_session,
        EventCreate(
            title="Прорыв трубы",
            body="На Лесной отключили воду",
            importance=2,
            source=EventSource.NEIGHBORS_CHAT,
            address_id=first_address.id,
            source_msg_id="msg-1",
        ),
    )
    assert created.id is not None
    assert created.address_id == first_address.id
    assert (created.lat, created.lon) == (55.75, 37.62)
    assert created.weight > 0
    assert created.image_url is None

    fetched = crud.get_event(db_session, created.id)
    assert fetched is not None
    assert fetched.title == "Прорыв трубы"

    updated = crud.update_event(
        db_session,
        created.id,
        EventUpdate(
            title="Прорыв трубы (обновлено)",
            importance=1,
            disaster_flag=False,
            address_id=second_address.id,
        ),
    )
    assert updated is not None
    assert updated.title.startswith("Прорыв")
    assert updated.importance == 1
    assert updated.address_id == second_address.id
    assert (updated.lat, updated.lon) == (55.751, 37.621)

    cleared = crud.update_event(db_session, created.id, EventUpdate(clear_address=True))
    assert cleared is not None
    assert cleared.address_id is None
    assert cleared.lat is None
    assert cleared.lon is None

    assert crud.delete_event(db_session, created.id) is True
    assert crud.get_event(db_session, created.id) is None


def test_unknown_address_is_rejected(db_session) -> None:
    with pytest.raises(ValueError, match="Адрес id=999 не найден"):
        crud.create_event(
            db_session,
            EventCreate(
                title="Нет адреса",
                body="x",
                importance=2,
                source="news",
                address_id=999,
            ),
        )


def test_create_with_and_without_image(db_session) -> None:
    address = add_address(db_session, lat=55.75, lon=37.62, suffix="3")
    with_photo = crud.create_event(
        db_session,
        EventCreate(
            title="С фото",
            body="x",
            importance=2,
            source="news",
            address_id=address.id,
            image_url="https://cdn.example/a.jpg",
        ),
    )
    assert with_photo.image_url == "https://cdn.example/a.jpg"

    no_photo = crud.create_event(
        db_session,
        EventCreate(
            title="Без фото",
            body="x",
            importance=2,
            source="news",
            address_id=address.id,
        ),
    )
    assert no_photo.image_url is None

    cleared = crud.update_event(
        db_session,
        with_photo.id,
        EventUpdate(clear_image=True),
    )
    assert cleared is not None
    assert cleared.image_url is None


def test_feed_nearby_city_and_cursor(db_session) -> None:
    seed_user_chat(
        db_session,
        max_user_id=4242,
        chat_id=900_001,
        lat=55.7500,
        lon=37.6200,
    )

    for i in range(5):
        address = add_address(
            db_session,
            lat=55.7500 + i * 0.0001,
            lon=37.6200,
            suffix=str(10 + i),
        )
        crud.create_event(
            db_session,
            EventCreate(
                title=f"Рядом {i}",
                body="x",
                importance=2,
                source="news",
                address_id=address.id,
                geo_by="street",
            ),
        )

    far_trivia = add_address(db_session, lat=55.85, lon=37.62, suffix="20")
    crud.create_event(
        db_session,
        EventCreate(
            title="Бытовуха далеко",
            body="x",
            importance=3,
            source="news",
            address_id=far_trivia.id,
            geo_by="street",
        ),
    )
    city_only = add_address(db_session, lat=55.84, lon=37.62, suffix="21")
    crud.create_event(
        db_session,
        EventCreate(
            title="Катастрофа город",
            body="x",
            importance=1,
            source="news",
            address_id=city_only.id,
            disaster_flag=True,
            geo_by="city",
        ),
    )
    # Без адреса — не в ленте.
    crud.create_event(
        db_session,
        EventCreate(
            title="Нет адреса",
            body="x",
            importance=2,
            source="news",
            address_id=None,
            geo_by="city",
        ),
    )
    # home тоже в nearby (~1.1 км — внутри 3 км)
    home_addr = add_address(db_session, lat=55.76, lon=37.63, suffix="22")
    crud.create_event(
        db_session,
        EventCreate(
            title="Дом рядом",
            body="x",
            importance=2,
            source="news",
            address_id=home_addr.id,
            geo_by="home",
        ),
    )
    # За радиусом nearby (~16 км) — отсекаем.
    beyond = add_address(db_session, lat=55.90, lon=37.62, suffix="23", street="Другая")
    crud.create_event(
        db_session,
        EventCreate(
            title="Слишком далеко",
            body="x",
            importance=2,
            source="news",
            address_id=beyond.id,
            geo_by="street",
        ),
    )

    page1 = crud.list_feed(
        db_session,
        scope="nearby",
        limit=2,
        max_user_id=4242,
    )
    assert len(page1.items) == 2
    assert page1.next_cursor is not None
    assert page1.origin is not None
    assert page1.origin.radius_m == 3000
    assert all(item.geo_by in ("street", "home") for item in page1.items)
    assert all(item.importance != 3 for item in page1.items)
    assert all(item.distance_m is not None and item.distance_m <= 3000 for item in page1.items)
    assert all(item.proximity is not None for item in page1.items)

    page2 = crud.list_feed(
        db_session,
        scope="nearby",
        limit=10,
        cursor=page1.next_cursor,
        max_user_id=4242,
    )
    ids1 = {item.id for item in page1.items}
    ids2 = {item.id for item in page2.items}
    assert ids1.isdisjoint(ids2)
    nearby_titles = {item.title for item in page1.items} | {item.title for item in page2.items}
    assert "Дом рядом" in nearby_titles
    assert "Катастрофа город" not in nearby_titles
    assert "Бытовуха далеко" not in nearby_titles
    assert "Слишком далеко" not in nearby_titles

    empty = crud.list_feed(db_session, scope="nearby", limit=20, max_user_id=999)
    assert empty.items == []
    assert empty.origin is None

    city = crud.list_feed(
        db_session,
        scope="city",
        limit=50,
    )
    titles = {item.title for item in city.items}
    assert "Бытовуха далеко" not in titles
    assert "Катастрофа город" in titles
    assert "Нет адреса" not in titles
    assert "Дом рядом" not in titles
    assert all(item.geo_by == "city" for item in city.items)


def test_nearby_closer_ranks_higher(db_session) -> None:
    seed_user_chat(
        db_session,
        max_user_id=100,
        chat_id=901_000,
        lat=55.75,
        lon=37.62,
        street="Лесная",
    )
    near = add_address(db_session, lat=55.7502, lon=37.6201, suffix="n", street="Лесная")
    mid = add_address(db_session, lat=55.758, lon=37.62, suffix="m", street="Другая")
    crud.create_event(
        db_session,
        EventCreate(
            title="Близко",
            body="x",
            importance=2,
            source="news",
            address_id=near.id,
            geo_by="street",
            published_at=datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
        ),
    )
    crud.create_event(
        db_session,
        EventCreate(
            title="Подальше",
            body="x",
            importance=2,
            source="news",
            address_id=mid.id,
            geo_by="street",
            published_at=datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
        ),
    )

    page = crud.list_feed(db_session, scope="nearby", limit=10, max_user_id=100)
    assert [item.title for item in page.items] == ["Близко", "Подальше"]
    assert page.items[0].distance_m < page.items[1].distance_m
    assert page.items[0].same_street is True
    assert page.items[1].same_street is False
    assert page.items[0].proximity in ("home", "block")


def test_nearby_active_window_boost(db_session) -> None:
    seed_user_chat(db_session, max_user_id=101, chat_id=901_001, lat=55.75, lon=37.62)
    now = datetime.now(UTC)
    a = add_address(db_session, lat=55.7501, lon=37.6201, suffix="a1")
    b = add_address(db_session, lat=55.7502, lon=37.6202, suffix="a2")
    crud.create_event(
        db_session,
        EventCreate(
            title="Сейчас",
            body="x",
            importance=2,
            source="news",
            address_id=a.id,
            geo_by="street",
            active_from=now - timedelta(hours=1),
            active_to=now + timedelta(hours=2),
            published_at=now - timedelta(hours=3),
        ),
    )
    crud.create_event(
        db_session,
        EventCreate(
            title="Просрочено",
            body="x",
            importance=2,
            source="news",
            address_id=b.id,
            geo_by="street",
            active_from=now - timedelta(days=3),
            active_to=now - timedelta(hours=1),
            published_at=now - timedelta(hours=3),
        ),
    )
    page = crud.list_feed(db_session, scope="nearby", limit=10, max_user_id=101)
    assert page.items[0].title == "Сейчас"
    assert page.items[0].is_active_now is True
    assert page.items[1].is_active_now is False


def test_map_excludes_trivia(db_session) -> None:
    water = add_address(db_session, lat=55.75, lon=37.62, suffix="30")
    cat = add_address(db_session, lat=55.751, lon=37.621, suffix="31")
    emergency = add_address(db_session, lat=55.752, lon=37.622, suffix="32")

    crud.create_event(
        db_session,
        EventCreate(
            title="Отключили воду",
            body="район Северный",
            importance=2,
            source="news",
            address_id=water.id,
        ),
    )
    crud.create_event(
        db_session,
        EventCreate(
            title="Пропала кошка",
            body="серая",
            importance=3,
            source="neighbors_chat",
            address_id=cat.id,
        ),
    )
    crud.create_event(
        db_session,
        EventCreate(
            title="ЧС",
            body="взрыв",
            importance=1,
            source="news",
            address_id=emergency.id,
            disaster_flag=True,
        ),
    )

    points = crud.list_map_points(db_session)
    titles = {p.title for p in points}
    assert "Отключили воду" in titles
    assert "ЧС" in titles
    assert "Пропала кошка" not in titles
    categories = {p.title: p.category for p in points}
    assert categories["ЧС"] == "catastrophe"
    assert categories["Отключили воду"] == "important"
