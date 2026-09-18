"""Тесты чистых функций веса и geo-правил."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from events.weight import (
    allowed_in_city_feed,
    allowed_in_feed,
    allowed_on_map,
    compute_weight,
    haversine_m,
    map_icon_category,
    matches_feed_geo,
    resolve_source_reliability,
    timeliness_score,
)


def test_compute_weight_importance_order() -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    w1 = compute_weight(importance=1, source="news", created_at=now, now=now)
    w2 = compute_weight(importance=2, source="news", created_at=now, now=now)
    w3 = compute_weight(importance=3, source="news", created_at=now, now=now)
    assert w1 > w2 > w3


def test_compute_weight_closer_is_heavier() -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    near = compute_weight(importance=2, source="news", distance_m=100, created_at=now, now=now)
    far = compute_weight(importance=2, source="news", distance_m=4000, created_at=now, now=now)
    assert near > far


def test_compute_weight_rejects_bad_importance() -> None:
    with pytest.raises(ValueError):
        compute_weight(importance=4, source="news")


def test_timeliness_decays() -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    fresh = timeliness_score(published_at=now, now=now)
    old = timeliness_score(published_at=now - timedelta(hours=48), now=now)
    assert fresh > old
    assert fresh == pytest.approx(1.0, abs=1e-6)


def test_outlet_reliability_from_config_map() -> None:
    assert resolve_source_reliability(
        source="news",
        source_msg_id="tass:123",
        outlet_reliability={"tass": 0.95},
    ) == pytest.approx(0.95)


def test_reliable_outlet_beats_weak() -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    strong = compute_weight(
        importance=2,
        source="news",
        source_msg_id="tass:1",
        created_at=now,
        now=now,
        outlet_reliability={"tass": 0.95, "mskagency": 0.5},
    )
    weak = compute_weight(
        importance=2,
        source="news",
        source_msg_id="mskagency:1",
        created_at=now,
        now=now,
        outlet_reliability={"tass": 0.95, "mskagency": 0.5},
    )
    assert strong > weak


def test_haversine_zero() -> None:
    assert haversine_m(55.75, 37.62, 55.75, 37.62) == pytest.approx(0.0, abs=1e-6)


def test_city_feed_hides_importance_1_unless_disaster() -> None:
    assert not allowed_in_city_feed(importance=1, disaster_flag=False)
    assert allowed_in_city_feed(importance=1, disaster_flag=True)
    assert allowed_in_city_feed(importance=2, disaster_flag=False)
    assert not allowed_in_city_feed(importance=3, disaster_flag=False)


def test_feed_rules_importance_and_geo() -> None:
    assert allowed_in_feed(importance=1)
    assert allowed_in_feed(importance=2)
    assert not allowed_in_feed(importance=3)
    assert matches_feed_geo(scope="nearby", geo_by="street")
    assert matches_feed_geo(scope="nearby", geo_by="home")
    assert not matches_feed_geo(scope="nearby", geo_by="city")
    assert matches_feed_geo(scope="city", geo_by="city")
    assert not matches_feed_geo(scope="city", geo_by="street")
    assert not matches_feed_geo(scope="city", geo_by=None)


def test_map_rules_and_categories() -> None:
    assert allowed_on_map(importance=1, disaster_flag=True)
    assert allowed_on_map(importance=2, disaster_flag=False)
    assert not allowed_on_map(importance=3, disaster_flag=False)
    assert not allowed_on_map(importance=0, disaster_flag=False)
    assert map_icon_category(importance=1, disaster_flag=True) == "catastrophe"
    assert map_icon_category(importance=2, disaster_flag=False) == "important"
