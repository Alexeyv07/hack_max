"""Тесты parse_lenta_rows (mskagency HTML)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from parse_news.sources.mskagency import parse_lenta_rows

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_lenta_rows_returns_ids_and_dates() -> None:
    html = (FIXTURES / "sample_mskagency_lenta.html").read_text(encoding="utf-8")
    rows = parse_lenta_rows(html)

    assert len(rows) == 2

    first_id, first_dt, first_title = rows[0]
    assert first_id == 111
    assert first_dt == datetime(2026, 9, 17, 10, 20, tzinfo=UTC)
    assert first_title == "Новость один"

    second_id, second_dt, second_title = rows[1]
    assert second_id == 222
    assert second_dt == datetime(2026, 9, 16, 14, 5, tzinfo=UTC)
    assert second_title == "Новость два"
