"""Тесты handlers: CRUD in-process + feed/map по memberships."""

from __future__ import annotations

from chat_link.models.membership import ChatMembership
from events.handlers import crud
from events.models.event import EventCreate, EventSource, EventUpdate

MOCK_MEMBERSHIPS = [
    ChatMembership(
        chat_id=1,
        title="demo",
        lat=55.75,
        lon=37.62,
        nearby_radius_m=3000,
        city_radius_m=30000,
    )
]


def test_create_get_update_delete(db_session) -> None:
    created = crud.create_event(
        db_session,
        EventCreate(
            title="Прорыв трубы",
            body="На Лесной отключили воду",
            importance=2,
            source=EventSource.NEIGHBORS_CHAT,
            lat=55.75,
            lon=37.62,
            source_msg_id="msg-1",
        ),
    )
    assert created.id is not None
    assert created.weight > 0
    assert created.image_url is None

    fetched = crud.get_event(db_session, created.id)
    assert fetched is not None
    assert fetched.title == "Прорыв трубы"

    updated = crud.update_event(
        db_session,
        created.id,
        EventUpdate(title="Прорыв трубы (обновлено)", importance=1, disaster_flag=False),
    )
    assert updated is not None
    assert updated.title.startswith("Прорыв")
    assert updated.importance == 1

    assert crud.delete_event(db_session, created.id) is True
    assert crud.get_event(db_session, created.id) is None


def test_create_with_and_without_image(db_session) -> None:
    with_photo = crud.create_event(
        db_session,
        EventCreate(
            title="С фото",
            body="x",
            importance=2,
            source="news",
            lat=55.75,
            lon=37.62,
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
            lat=55.75,
            lon=37.62,
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
        crud.create_event(
            db_session,
            EventCreate(
                title=f"Рядом {i}",
                body="x",
                importance=2,
                source="news",
                lat=55.7500 + i * 0.0001,
                lon=37.6200,
            ),
        )
    crud.create_event(
        db_session,
        EventCreate(
            title="Бытовуха далеко",
            body="x",
            importance=3,
            source="news",
            lat=55.85,
            lon=37.62,
        ),
    )
    crud.create_event(
        db_session,
        EventCreate(
            title="Катастрофа город",
            body="x",
            importance=1,
            source="news",
            lat=55.84,
            lon=37.62,
            disaster_flag=True,
        ),
    )

    page1 = crud.list_feed(
        db_session,
        scope="nearby",
        memberships=MOCK_MEMBERSHIPS,
        limit=2,
    )
    assert len(page1.items) == 2
    assert page1.next_cursor is not None

    page2 = crud.list_feed(
        db_session,
        scope="nearby",
        memberships=MOCK_MEMBERSHIPS,
        limit=2,
        cursor=page1.next_cursor,
    )
    ids1 = {item.id for item in page1.items}
    ids2 = {item.id for item in page2.items}
    assert ids1.isdisjoint(ids2)

    city = crud.list_feed(
        db_session,
        scope="city",
        memberships=MOCK_MEMBERSHIPS,
        limit=50,
    )
    titles = {item.title for item in city.items}
    assert "Бытовуха далеко" in titles
    assert "Катастрофа город" in titles


def test_map_excludes_trivia(db_session) -> None:
    crud.create_event(
        db_session,
        EventCreate(
            title="Отключили воду",
            body="район Северный",
            importance=2,
            source="news",
            lat=55.75,
            lon=37.62,
        ),
    )
    crud.create_event(
        db_session,
        EventCreate(
            title="Пропала кошка",
            body="серая",
            importance=3,
            source="neighbors_chat",
            lat=55.751,
            lon=37.621,
        ),
    )
    crud.create_event(
        db_session,
        EventCreate(
            title="ЧС",
            body="взрыв",
            importance=1,
            source="news",
            lat=55.752,
            lon=37.622,
            disaster_flag=True,
        ),
    )

    points = crud.list_map_points(db_session, memberships=MOCK_MEMBERSHIPS)
    titles = {p.title for p in points}
    assert "Отключили воду" in titles
    assert "ЧС" in titles
    assert "Пропала кошка" not in titles
    categories = {p.title: p.category for p in points}
    assert categories["ЧС"] == "catastrophe"
    assert categories["Отключили воду"] == "important"
