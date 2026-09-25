"""Тесты HTTP API: feed + map по X-Max-User-Id (nearby персонально)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from address.db.address import AddressRow
from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload
from events.api.app import create_app
from events.api.deps import get_db_session
from events.handlers import crud
from events.models.event import EventCreate
from project.config import reset_settings_cache
from user_chat.handlers import add_chat_address, add_user_to_chat, create_chat, set_member_address
from user_chat.models import ChatCreate

USER_HEADERS = {"X-Max-User-Id": "4242"}


@pytest.fixture()
def client(session_factory, monkeypatch):
    reset_settings_cache()
    monkeypatch.setenv("APP_ENVIRONMENT", "local")

    def _override_db():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db_session] = _override_db
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()
    reset_settings_cache()


def _add_address(
    session,
    *,
    text: str,
    lat: float,
    lon: float,
    street: str | None = "Тестовая",
    city: str | None = "Москва",
) -> AddressRow:
    row = AddressRow(
        address_text=text,
        postal_code="123456",
        city=city,
        street=street,
        latitude=Decimal(str(lat)),
        longitude=Decimal(str(lon)),
    )
    session.add(row)
    session.flush()
    return row


def _seed_user_and_events(session_factory) -> None:
    session = session_factory()
    try:
        authorize_user(
            session,
            MaxUserPayload(max_user_id=4242, name="Demo", username="demo"),
        )
        nearby = _add_address(
            session, text="Москва, улица Тестовая, д. 1", lat=55.7505, lon=37.6202
        )
        create_chat(session, ChatCreate(chat_id=900_001, address_id=nearby.id))
        add_user_to_chat(session, 900_001, max_user_id=4242)
        set_member_address(session, 900_001, max_user_id=4242, address_id=nearby.id)
        cat = _add_address(session, text="Москва, улица Тестовая, д. 2", lat=55.751, lon=37.621)
        far = _add_address(session, text="Москва, улица Тестовая, д. 3", lat=55.90, lon=37.62)
        crud.create_event(
            session,
            EventCreate(
                title="Nearby ok",
                body="b",
                importance=2,
                source="news",
                address_id=nearby.id,
                image_url="https://cdn.example/nearby.jpg",
                geo_by="street",
            ),
        )
        crud.create_event(
            session,
            EventCreate(
                title="Пропала кошка",
                body="b",
                importance=3,
                source="neighbors_chat",
                address_id=cat.id,
                geo_by="street",
            ),
        )
        crud.create_event(
            session,
            EventCreate(
                title="Far city",
                body="b",
                importance=2,
                source="news",
                address_id=far.id,
                geo_by="city",
            ),
        )
        crud.create_event(
            session,
            EventCreate(
                title="Вода в районе",
                body="отключили",
                importance=2,
                source="news",
                address_id=nearby.id,
                geo_by="home",
            ),
        )
        # Без адреса — не должно попасть в ленту.
        crud.create_event(
            session,
            EventCreate(
                title="Без локации",
                body="skip",
                importance=2,
                source="news",
                address_id=None,
                geo_by="city",
            ),
        )
        # За радиусом — не в nearby.
        beyond = _add_address(
            session,
            text="Москва, далеко",
            lat=56.20,
            lon=37.70,
            street="Далёкая",
        )
        crud.create_event(
            session,
            EventCreate(
                title="Beyond radius",
                body="b",
                importance=2,
                source="news",
                address_id=beyond.id,
                geo_by="street",
            ),
        )
        session.commit()
    finally:
        session.close()


def test_health(client) -> None:
    test_client, _ = client
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_feed_requires_user_header(client) -> None:
    test_client, _ = client
    response = test_client.get("/events/feed", params={"scope": "nearby"})
    assert response.status_code == 401


def test_feed_empty_without_selected_home(client) -> None:
    """Без выбранного дома nearby пустой; городская лента всё ещё доступна."""
    test_client, session_factory = client
    _seed_user_and_events(session_factory)
    response = test_client.get(
        "/events/feed",
        params={"scope": "nearby"},
        headers={"X-Max-User-Id": "999"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["origin"] is None

    city = test_client.get(
        "/events/feed",
        params={"scope": "city"},
        headers={"X-Max-User-Id": "999"},
    )
    assert city.status_code == 200
    assert "Far city" in {item["title"] for item in city.json()["items"]}


def test_feed_selected_address(client) -> None:
    test_client, session_factory = client
    _seed_user_and_events(session_factory)

    first = test_client.get(
        "/events/feed",
        params={"scope": "nearby", "limit": 1},
        headers=USER_HEADERS,
    )
    assert first.status_code == 200
    body = first.json()
    assert body["count"] == 1
    assert body["next_cursor"] is not None
    assert body["origin"] is not None
    assert body["origin"]["radius_m"] == 6_000
    item = body["items"][0]
    assert item["lat"] is not None
    assert item["lon"] is not None
    assert item["location"]
    assert item["distance_m"] is not None
    assert item["proximity"] in ("home", "block", "street", "district")
    assert "published_at" in item

    full = test_client.get(
        "/events/feed",
        params={"scope": "nearby", "limit": 50},
        headers=USER_HEADERS,
    )
    assert full.status_code == 200
    by_title = {i["title"]: i for i in full.json()["items"]}
    assert by_title["Nearby ok"]["image_url"] == "https://cdn.example/nearby.jpg"
    assert "Вода в районе" in by_title
    assert "Beyond radius" not in by_title
    assert "Без локации" not in by_title


def test_map_only_important(client) -> None:
    test_client, session_factory = client
    _seed_user_and_events(session_factory)

    response = test_client.get("/events/map", headers=USER_HEADERS)
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert "Nearby ok" in titles
    assert "Вода в районе" in titles
    assert "Пропала кошка" not in titles
    by_title = {item["title"]: item for item in response.json()["items"]}
    assert by_title["Nearby ok"]["geo_by"] == "street"
    assert by_title["Nearby ok"]["location"] == "Москва, Тестовая"
    assert "Far city" not in by_title


def test_nearby_differs_by_user_location(client) -> None:
    test_client, session_factory = client
    _seed_user_and_events(session_factory)
    with session_factory.begin() as session:
        authorize_user(session, MaxUserPayload(max_user_id=999))
        address = _add_address(
            session,
            text="Москва, дом второго пользователя",
            lat=56.20,
            lon=37.70,
            street="Далёкая",
        )
        create_chat(session, ChatCreate(chat_id=900_002, address_id=address.id))
        add_user_to_chat(session, 900_002, max_user_id=999)
        set_member_address(session, 900_002, max_user_id=999, address_id=address.id)

    a = test_client.get("/events/feed", params={"scope": "nearby"}, headers=USER_HEADERS)
    b = test_client.get(
        "/events/feed", params={"scope": "nearby"}, headers={"X-Max-User-Id": "999"}
    )
    assert a.status_code == 200 and b.status_code == 200
    titles_a = {i["title"] for i in a.json()["items"]}
    titles_b = {i["title"] for i in b.json()["items"]}
    assert "Nearby ok" in titles_a
    assert "Beyond radius" not in titles_a
    assert "Beyond radius" in titles_b
    assert "Nearby ok" not in titles_b


def test_write_endpoints_removed(client) -> None:
    test_client, _ = client
    assert test_client.post("/events", json={}).status_code in {404, 405}
    assert test_client.patch("/events/1", json={}).status_code in {404, 405}
    assert test_client.delete("/events/1").status_code in {404, 405}


def test_same_courtyard_chat_has_separate_home_feeds(client) -> None:
    test_client, session_factory = client
    with session_factory.begin() as session:
        first = _add_address(session, text="Москва, двор 1", lat=55.75, lon=37.62)
        second = _add_address(session, text="Москва, двор 2", lat=55.7502, lon=37.6202)
        authorize_user(session, MaxUserPayload(max_user_id=4242))
        authorize_user(session, MaxUserPayload(max_user_id=999))
        create_chat(session, ChatCreate(chat_id=900_010, address_id=first.id))
        add_chat_address(session, 900_010, second.id)
        add_user_to_chat(session, 900_010, max_user_id=4242)
        add_user_to_chat(session, 900_010, max_user_id=999)
        set_member_address(session, 900_010, max_user_id=4242, address_id=first.id)
        set_member_address(session, 900_010, max_user_id=999, address_id=second.id)
        for title, address in (("Работы в первом доме", first), ("Работы во втором доме", second)):
            crud.create_event(
                session,
                EventCreate(
                    title=title,
                    body="Отключение",
                    importance=2,
                    source="news",
                    address_id=address.id,
                    geo_by="home",
                ),
            )

    one = test_client.get("/events/feed", params={"scope": "nearby"}, headers=USER_HEADERS)
    two = test_client.get(
        "/events/feed", params={"scope": "nearby"}, headers={"X-Max-User-Id": "999"}
    )
    assert one.status_code == two.status_code == 200
    assert [item["title"] for item in one.json()["items"]] == ["Работы в первом доме"]
    assert [item["title"] for item in two.json()["items"]] == ["Работы во втором доме"]


def test_personal_address_nearby_without_group(client) -> None:
    """Старый личный адрес v5 не открывает nearby без подтверждённого чата."""
    from auth.handlers.residence import set_personal_address

    test_client, factory = client
    with factory() as session:
        authorize_user(session, MaxUserPayload(max_user_id=4242, name="Resident"))
        authorize_user(session, MaxUserPayload(max_user_id=5555, name="Another"))
        home = _add_address(
            session, text="Москва, улица Мира, д. 1", lat=55.75, lon=37.62, street="Мира"
        )
        second = _add_address(
            session, text="Москва, далеко, д. 2", lat=55.94, lon=37.82, street="Далёкая"
        )
        crud.create_event(
            session,
            EventCreate(
                title="Рядом с домом",
                body="Ремонт",
                importance=2,
                source="news",
                address_id=home.id,
                geo_by="street",
            ),
        )
        crud.create_event(
            session,
            EventCreate(
                title="Чужой дом",
                body="Детали",
                importance=2,
                source="news",
                address_id=second.id,
                geo_by="home",
            ),
        )
        set_personal_address(session, max_user_id=4242, address_id=home.id)
        session.commit()
    nearby = test_client.get("/events/feed", params={"scope": "nearby"}, headers=USER_HEADERS)
    assert nearby.status_code == 200
    payload = nearby.json()
    assert payload["items"] == []
    assert payload["origin"] is None
    own = test_client.get("/chat-link/residence", headers=USER_HEADERS)
    assert own.status_code == 200 and own.json()["address"] is None
    another = test_client.get("/chat-link/residence", headers={"X-Max-User-Id": "5555"})
    assert another.status_code == 200 and another.json()["address"] is None
    no_origin = test_client.get(
        "/events/feed", params={"scope": "nearby"}, headers={"X-Max-User-Id": "5555"}
    )
    assert no_origin.status_code == 200 and no_origin.json()["origin"] is None


def test_unconfirmed_personal_location_falls_back_to_linked_group(client) -> None:
    """Дом, добавленный к группе, не должен менять личную точку для новостей."""
    from auth.handlers.residence import set_personal_address

    test_client, factory = client
    with factory() as session:
        authorize_user(session, MaxUserPayload(max_user_id=4242))
        own = _add_address(
            session, text="Москва, личный дом", lat=55.75, lon=37.62, street="Личная"
        )
        group = _add_address(
            session, text="Москва, групповая улица", lat=55.94, lon=37.82, street="Групповая"
        )
        create_chat(session, ChatCreate(chat_id=900_001, address_id=group.id))
        add_user_to_chat(session, 900_001, max_user_id=4242)
        set_member_address(session, 900_001, max_user_id=4242, address_id=group.id)
        set_personal_address(session, max_user_id=4242, address_id=own.id)
        crud.create_event(
            session,
            EventCreate(
                title="Около личного",
                body="Текст",
                importance=2,
                source="news",
                address_id=own.id,
                geo_by="street",
            ),
        )
        crud.create_event(
            session,
            EventCreate(
                title="Около группового",
                body="Текст",
                importance=2,
                source="news",
                address_id=group.id,
                geo_by="street",
            ),
        )
        session.commit()
    response = test_client.get("/events/feed", params={"scope": "nearby"}, headers=USER_HEADERS)
    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == ["Около группового"]
    assert response.json()["origin"]["chat_count"] == 1


def test_street_only_event_uses_approximate_street_center(client) -> None:
    """A street-level event must not appear pinned to a random house."""
    test_client, session_factory = client
    with session_factory() as session:
        first = _add_address(
            session,
            text="Москва, улица Средняя, д. 1",
            lat=55.76,
            lon=37.62,
            street="улица Средняя",
        )
        _add_address(
            session,
            text="Москва, улица Средняя, д. 2",
            lat=55.78,
            lon=37.64,
            street="улица Средняя",
        )
        street_event = crud.create_event(
            session,
            EventCreate(
                title="Известна только улица",
                body="b",
                importance=2,
                source="news",
                address_id=first.id,
                geo_by="street",
            ),
        )
        home_event = crud.create_event(
            session,
            EventCreate(
                title="Точный дом",
                body="b",
                importance=2,
                source="news",
                address_id=first.id,
                geo_by="home",
            ),
        )
        city = _add_address(session, text="Москва", lat=55.7558, lon=37.6173, street=None)
        city_event = crud.create_event(
            session,
            EventCreate(
                title="Известен только город",
                body="b",
                importance=2,
                source="news",
                address_id=city.id,
                geo_by="city",
            ),
        )
        session.commit()

    response = test_client.get("/events/feed", params={"scope": "city"}, headers=USER_HEADERS)
    assert response.status_code == 200
    feed = {item["id"]: item for item in response.json()["items"]}
    assert feed[street_event.id]["lat"] == pytest.approx(55.77)
    assert feed[street_event.id]["lon"] == pytest.approx(37.63)
    assert feed[street_event.id]["location"] == "Москва, улица Средняя"
    assert feed[street_event.id]["geo_by"] == "street"
    assert feed[home_event.id]["lat"] == pytest.approx(55.76)
    assert feed[home_event.id]["lon"] == pytest.approx(37.62)

    response = test_client.get("/events/map", headers=USER_HEADERS)
    assert response.status_code == 200
    points = {item["id"]: item for item in response.json()["items"]}
    assert points[street_event.id]["lat"] == pytest.approx(55.77)
    assert points[street_event.id]["lon"] == pytest.approx(37.63)
    assert points[street_event.id]["location"] == "Москва, улица Средняя"
    assert points[home_event.id]["lon"] == pytest.approx(37.62)
    assert city_event.id not in points
