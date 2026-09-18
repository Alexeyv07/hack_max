"""Тесты разбора address_text → city/street/house."""

from __future__ import annotations

from address.components import build_address_text, parse_address_text


def test_parse_full_address() -> None:
    parsed = parse_address_text("Москва, улица Тестовая, д. 1")
    assert parsed.city == "Москва"
    assert parsed.street == "улица Тестовая"
    assert parsed.house == "1"


def test_parse_city_only() -> None:
    parsed = parse_address_text("Москва")
    assert parsed.city == "Москва"
    assert parsed.street is None
    assert parsed.house is None


def test_build_address_text() -> None:
    assert build_address_text(city="Москва", street="улица А", house="10") == (
        "Москва, улица А, д. 10"
    )
