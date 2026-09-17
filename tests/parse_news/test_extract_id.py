"""Тесты extract_id_from_url и ссылок из HTML-фикстур."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from parse_news.sources.common import extract_id_from_url, find_links

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://tass.ru/obschestvo/1234567", "1234567"),
        ("https://ria.ru/20260917/foo-2118199709.html", "2118199709"),
        ("https://www.kommersant.ru/doc/1234567", "1234567"),
        ("https://msk1.ru/text/incidents/2026/09/10/76634109/", "76634109"),
        ("https://www.m24.ru/news/17092026/9876543", "9876543"),
        ("https://www.mskagency.ru/materials/555", "555"),
    ],
)
def test_extract_id_from_url(url: str, expected: str) -> None:
    assert extract_id_from_url(url) == expected


def test_extract_id_from_kommersant_fixture() -> None:
    html = (FIXTURES / "sample_kommersant_listing.html").read_text(encoding="utf-8")
    links = find_links(
        html,
        base_url="https://www.kommersant.ru/rubric/6",
        href_pattern=re.compile(r"/doc/\d+"),
    )
    ids = [extract_id_from_url(url) for url, _ in links]
    assert ids == ["1234567", "7654321", "99999"]


def test_extract_id_from_msk1_fixture() -> None:
    html = (FIXTURES / "sample_msk1_listing.html").read_text(encoding="utf-8")
    links = find_links(
        html,
        base_url="https://msk1.ru/text/",
        href_pattern=re.compile(r"/text/[^/]+/\d{4}/\d{2}/\d{2}/\d+/?"),
    )
    ids = [extract_id_from_url(url) for url, _ in links]
    assert ids == ["76634109", "76635001"]
