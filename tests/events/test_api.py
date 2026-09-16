"""Тесты HTTP API: feed + map по X-Max-User-Id и mock-чатам."""

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
            ),
        )
        crud.create_event(
            session,
            EventCreate(
                title="Far city",
                body="b",
                importance=3,
                source="news",
                address_id=far.id,
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


def test_feed_unknown_user(client) -> None:
    test_client, _ = client
    response = test_client.get(
        "/events/feed",
        params={"scope": "nearby"},
        headers={"X-Max-User-Id": "999"},
    )
    assert response.status_code == 404


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
    assert body["items"][0]["image_url"] == "https://cdn.example/nearby.jpg"
    assert body["items"][0]["lat"] == 55.75
    assert body["items"][0]["lon"] == 37.62

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
    assert "Far city" not in titles


def test_write_endpoints_removed(client) -> None:
    test_client, _ = client
    assert test_client.post("/events", json={}).status_code in {404, 405}
    assert test_client.patch("/events/1", json={}).status_code in {404, 405}
    assert test_client.delete("/events/1").status_code in {404, 405}
