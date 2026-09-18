"""Тесты HTTP API: feed + map по X-Max-User-Id (общая лента)."""

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
from user_chat.handlers import add_user_to_chat, create_chat
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


def _add_address(session, *, text: str, lat: float, lon: float) -> AddressRow:
    row = AddressRow(
        address_text=text,
        postal_code="123456",
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
        nearby = _add_address(session, text="Москва, улица Тестовая, д. 1", lat=55.75, lon=37.62)
        create_chat(session, ChatCreate(chat_id=900_001, address_id=nearby.id))
        add_user_to_chat(session, 900_001, max_user_id=4242)
        cat = _add_address(session, text="Москва, улица Тестовая, д. 2", lat=55.751, lon=37.621)
        far = _add_address(session, text="Москва, улица Тестовая, д. 3", lat=55.90, lon=37.62)
        water = _add_address(session, text="Москва, улица Тестовая, д. 4", lat=55.80, lon=37.62)

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
                address_id=water.id,
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


def test_feed_shared_for_any_user_id(client) -> None:
    """Header обязателен, чаты не нужны — одна лента всем."""
    test_client, session_factory = client
    _seed_user_and_events(session_factory)
    response = test_client.get(
        "/events/feed",
        params={"scope": "nearby"},
        headers={"X-Max-User-Id": "999"},
    )
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert "Nearby ok" in titles
    assert "Вода в районе" in titles
    assert "Far city" not in titles
    assert "Пропала кошка" not in titles
    assert "Без локации" not in titles


def test_feed_and_cursor(client) -> None:
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
    item = body["items"][0]
    assert item["lat"] is not None
    assert item["lon"] is not None
    assert item["location"]
    assert "published_at" in item

    full = test_client.get(
        "/events/feed",
        params={"scope": "nearby", "limit": 50},
        headers=USER_HEADERS,
    )
    assert full.status_code == 200
    by_title = {i["title"]: i for i in full.json()["items"]}
    assert by_title["Nearby ok"]["image_url"] == "https://cdn.example/nearby.jpg"
    assert "Без локации" not in by_title

    second = test_client.get(
        "/events/feed",
        params={"scope": "nearby", "limit": 1, "cursor": body["next_cursor"]},
        headers=USER_HEADERS,
    )
    assert second.status_code == 200
    assert first.json()["items"][0]["id"] != second.json()["items"][0]["id"]


def test_map_only_important(client) -> None:
    test_client, session_factory = client
    _seed_user_and_events(session_factory)

    response = test_client.get("/events/map", headers=USER_HEADERS)
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert "Nearby ok" in titles
    assert "Вода в районе" in titles
    assert "Пропала кошка" not in titles


def test_same_feed_for_different_users(client) -> None:
    test_client, session_factory = client
    _seed_user_and_events(session_factory)
    with session_factory.begin() as session:
        authorize_user(session, MaxUserPayload(max_user_id=999))
        address = _add_address(
            session, text="Москва, дом второго пользователя", lat=55.90, lon=37.62
        )
        create_chat(session, ChatCreate(chat_id=900_002, address_id=address.id))
        add_user_to_chat(session, 900_002, max_user_id=999)

    a = test_client.get("/events/feed", params={"scope": "nearby"}, headers=USER_HEADERS)
    b = test_client.get(
        "/events/feed", params={"scope": "nearby"}, headers={"X-Max-User-Id": "999"}
    )
    assert a.status_code == 200 and b.status_code == 200
    assert [i["id"] for i in a.json()["items"]] == [i["id"] for i in b.json()["items"]]


def test_write_endpoints_removed(client) -> None:
    test_client, _ = client
    assert test_client.post("/events", json={}).status_code in {404, 405}
    assert test_client.patch("/events/1", json={}).status_code in {404, 405}
    assert test_client.delete("/events/1").status_code in {404, 405}
