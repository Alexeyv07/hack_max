"""Тесты handlers: CRUD in-process + feed/map."""

from __future__ import annotations

from decimal import Decimal

import pytest

from address.db.address import AddressRow
from events.handlers import crud
from events.models.event import EventCreate, EventSource, EventUpdate


def add_address(db_session, *, lat: float, lon: float, suffix: str) -> AddressRow:
    row = AddressRow(
        address_text=f"Москва, улица Тестовая, д. {suffix}",
        postal_code="123456",
        latitude=Decimal(str(lat)),
        longitude=Decimal(str(lon)),
    )
    db_session.add(row)
    db_session.flush()
    return row


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
    # home тоже в nearby
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

    page1 = crud.list_feed(
        db_session,
        scope="nearby",
        limit=2,
    )
    assert len(page1.items) == 2
    assert page1.next_cursor is not None
    assert all(item.geo_by in ("street", "home") for item in page1.items)
    assert all(item.importance != 3 for item in page1.items)

    page2 = crud.list_feed(
        db_session,
        scope="nearby",
        limit=4,
        cursor=page1.next_cursor,
    )
    ids1 = {item.id for item in page1.items}
    ids2 = {item.id for item in page2.items}
    assert ids1.isdisjoint(ids2)
    nearby_titles = {item.title for item in page1.items} | {item.title for item in page2.items}
    assert "Дом рядом" in nearby_titles
    assert "Катастрофа город" not in nearby_titles
    assert "Бытовуха далеко" not in nearby_titles

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


def test_feed_same_for_all(db_session) -> None:
    address = add_address(db_session, lat=55.75, lon=37.62, suffix="40")
    created = crud.create_event(
        db_session,
        EventCreate(
            title="Общее",
            body="x",
            importance=2,
            source="news",
            address_id=address.id,
            geo_by="street",
        ),
    )
    assert created.location == address.address_text

    page = crud.list_feed(
        db_session,
        scope="nearby",
        limit=20,
    )
    assert [item.id for item in page.items] == [created.id]
    assert page.items[0].location


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
