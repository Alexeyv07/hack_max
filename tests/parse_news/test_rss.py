"""Тесты parser_common.rss (без сети)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from parser_common.rss import parse_rss

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_rss_extracts_items_titles_dates() -> None:
    xml_text = (FIXTURES / "sample_rss.xml").read_text(encoding="utf-8")
    items = parse_rss(xml_text)

    assert len(items) == 2

    first, second = items
    assert first.title == "Первая новость"
    assert first.link == "https://tass.ru/obschestvo/1234567"
    assert first.guid == "https://tass.ru/obschestvo/1234567"
    assert first.published_at == datetime(2026, 9, 17, 7, 0, tzinfo=UTC)
    assert first.description == "Краткое описание первой новости."

    assert second.title == "Вторая новость"
    assert second.link == "https://ria.ru/20260917/vtoraya-7654321.html"
    assert second.published_at == datetime(2026, 9, 17, 8, 30, tzinfo=UTC)
    assert second.description == "Вторая новость без HTML."
