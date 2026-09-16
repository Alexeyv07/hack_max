"""Тесты чистых функций веса и geo-правил."""

from __future__ import annotations

import pytest

from events.weight import (
    allowed_in_city_feed,
    allowed_on_map,
    compute_weight,
    haversine_m,
    map_icon_category,
)


def test_compute_weight_importance_order() -> None:
    w1 = compute_weight(importance=1, source="news")
    w2 = compute_weight(importance=2, source="news")
    w3 = compute_weight(importance=3, source="news")
    assert w1 > w2 > w3


def test_compute_weight_closer_is_heavier() -> None:
    near = compute_weight(importance=2, source="news", distance_m=100)
    far = compute_weight(importance=2, source="news", distance_m=4000)
    assert near > far


def test_compute_weight_rejects_bad_importance() -> None:
    with pytest.raises(ValueError):
        compute_weight(importance=4, source="news")


def test_haversine_zero() -> None:
    assert haversine_m(55.75, 37.62, 55.75, 37.62) == pytest.approx(0.0, abs=1e-6)


def test_city_feed_hides_importance_1_unless_disaster() -> None:
    assert not allowed_in_city_feed(importance=1, disaster_flag=False)
    assert allowed_in_city_feed(importance=1, disaster_flag=True)
    assert allowed_in_city_feed(importance=2, disaster_flag=False)


def test_map_rules_and_categories() -> None:
    assert allowed_on_map(importance=1, disaster_flag=True)
    assert allowed_on_map(importance=2, disaster_flag=False)
    assert not allowed_on_map(importance=3, disaster_flag=False)
    assert not allowed_on_map(importance=0, disaster_flag=False)
    assert map_icon_category(importance=1, disaster_flag=True) == "catastrophe"
    assert map_icon_category(importance=2, disaster_flag=False) == "important"
