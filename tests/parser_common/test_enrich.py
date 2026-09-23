"""Тесты place_ner и time_extract (без обязательных ML-артефактов)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from address.geocoding import GeoMatcher
from address.models.address import Address
from address.street_catalog import StreetCatalog, StreetEntry, street_alias_keys
from parser_common.place_ner import resolve_place_to_address
from parser_common.time_extract import extract_active_window
from parser_common.time_onnx import TimeWindowPrediction


def test_time_extract_none_without_model() -> None:
    # Без артефактов — none; с артефактами в окружении — onnx (оба валидны).
    result = extract_active_window("Отключение с 10:00 до 18:00", use_model=True)
    assert result.method in ("none", "onnx")
    if result.method == "none":
        assert result.active_from is None
        assert result.active_to is None


def test_time_extract_uses_onnx_mock() -> None:
    ref = datetime(2026, 3, 12, 12, 0, tzinfo=UTC)
    fake = TimeWindowPrediction(
        active_from=ref.replace(hour=10),
        active_to=ref.replace(hour=18),
        confidence=0.9,
        method="onnx",
    )
    with patch(
        "parser_common.time_extract.predict_time_window_onnx",
        return_value=fake,
    ):
        result = extract_active_window("с 10 до 18", reference=ref, use_model=True)
    assert result.method == "onnx"
    assert result.active_from is not None
    assert result.active_to is not None


def test_place_resolve_via_catalog() -> None:
    entry = StreetEntry(
        city="Москва",
        canonical="улица Ленина",
        pin_id=42,
        houses={"10": 99},
        keys=street_alias_keys("улица Ленина"),
    )
    catalog = StreetCatalog([entry])
    hit = resolve_place_to_address(
        "Авария на улице Ленина дом 10",
        street_catalog=catalog,
        prefer_spacy=False,
    )
    assert hit is not None
    assert hit.address_id in {42, 99}
    assert hit.method == "catalog"


def test_place_resolve_geo_matcher_fallback() -> None:
    matcher = GeoMatcher(
        [
            Address(
                id=7,
                postal_code="101000",
                address_text="Москва, улица Тверская, дом 1",
                latitude=Decimal("55.76"),
                longitude=Decimal("37.61"),
            )
        ],
        threshold=80,
        margin=5,
    )
    hit = resolve_place_to_address(
        "на улице Тверская дом 1 затопление",
        street_catalog=None,
        geo_matcher=matcher,
        prefer_spacy=False,
    )
    assert hit is not None
    assert hit.address_id == 7
