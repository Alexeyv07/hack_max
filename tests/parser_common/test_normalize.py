"""Тесты parser_common: classify + normalize."""

from __future__ import annotations

from decimal import Decimal

from address.geocoding import GeoMatcher
from address.models.address import Address
from events.models.event import EventCreate
from parser_common import EventDraft, ParserCandidate, normalize, to_event_create
from parser_common.classify import classify_importance, clear_rules_cache


def test_classify_disaster() -> None:
    result = classify_importance("В районе землетрясение, объявлена эвакуация")
    assert result.importance == 1
    assert result.disaster_flag is True


def test_classify_important_water() -> None:
    result = classify_importance("Отключили воду на Лесной до вечера")
    assert result.importance == 2
    assert result.disaster_flag is False


def test_classify_trivia() -> None:
    result = classify_importance("Пропала серая кошка, отзовитесь")
    assert result.importance == 3


def test_normalize_news_keeps_title() -> None:
    draft = normalize(
        ParserCandidate(
            raw_text="длинный текст новости ...",
            source="news",
            title="Прорыв трубы на Севере",
            body="Без воды дома 1–5",
            source_msg_id="n-1",
            source_url="https://example.com/n",
        )
    )
    assert draft.title == "Прорыв трубы на Севере"
    assert "Без воды" in draft.body
    assert draft.importance == 2
    assert draft.source == "news"
    assert draft.source_url == "https://example.com/n"


def test_normalize_chat_builds_title_from_raw() -> None:
    draft = normalize(
        ParserCandidate(
            raw_text="Отключили свет\nУже третий час темно во дворе",
            source="neighbors_chat",
            source_msg_id="m-9",
        )
    )
    assert draft.title == "Отключили свет"
    assert "третий час" in draft.body
    assert draft.importance == 2


def test_normalize_with_geo_matcher() -> None:
    matcher = GeoMatcher(
        [
            Address(
                id=42,
                postal_code="101000",
                address_text="Москва, улица Ленина, дом 10",
                latitude=Decimal("55.75"),
                longitude=Decimal("37.62"),
            )
        ],
        threshold=80,
        margin=5,
    )
    draft = normalize(
        ParserCandidate(
            raw_text="На улице Ленина дом 10 отключили воду",
            source="neighbors_chat",
            geo_text="улица Ленина дом 10",
        ),
        geo_matcher=matcher,
    )
    assert draft.address_id == 42
    assert draft.geo_method in {"fuzzy", "postcode"}
    assert draft.importance == 2


def test_to_event_create() -> None:
    draft = EventDraft(
        title="t",
        body="b",
        importance=3,
        source="manual",
        address_id=7,
        image_url="https://cdn/x.jpg",
    )
    create = to_event_create(draft)
    assert isinstance(create, EventCreate)
    assert create.address_id == 7
    assert create.image_url == "https://cdn/x.jpg"


def test_rules_yaml_extra_keyword(monkeypatch, tmp_path) -> None:
    rules = tmp_path / "rules.yaml"
    rules.write_text("disaster:\n  - уникальныймаркеркатастрофы\n", encoding="utf-8")
    monkeypatch.setattr("parser_common.classify._RULES_PATH", rules)
    clear_rules_cache()
    try:
        result = classify_importance("Сегодня уникальныймаркеркатастрофы в городе")
        assert result.importance == 1
        assert result.disaster_flag is True
    finally:
        clear_rules_cache()
