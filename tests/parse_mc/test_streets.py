"""Тесты extract_street_lines / dedupe."""

from __future__ import annotations

from parser_common.geo_text import extract_street_lines


def test_extract_street_lines_multi() -> None:
    text = (
        "Отключение ГВС по адресам:\n"
        "Варшавское шоссе, д.47\n"
        "ул. Высокая, д.5\n"
        "Нагатинская наб., д.10\n"
    )
    streets = extract_street_lines(text)
    assert len(streets) >= 2
    joined = " ".join(streets).lower()
    assert "варшавск" in joined or "высокая" in joined or "нагатин" in joined
