"""Тесты parser_common: classify + normalize (+ mock ONNX)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from address.geocoding import GeoMatcher
from address.models.address import Address
from events.models.event import EventCreate
from parser_common import EventDraft, ParserCandidate, normalize, to_event_create
from parser_common.classify import (
    classify_by_rules,
    classify_importance,
    clear_rules_cache,
)
from parser_common.model_onnx import ModelPrediction


def test_classify_disaster() -> None:
    result = classify_importance(
        "В районе землетрясение, объявлена эвакуация",
        use_model=False,
    )
    assert result.importance == 1
    assert result.disaster_flag is True
    assert result.method == "rules"


def test_classify_important_water() -> None:
    result = classify_importance("Отключили воду на Лесной до вечера", use_model=False)
    assert result.importance == 2
    assert result.disaster_flag is False


def test_classify_trivia() -> None:
    result = classify_importance("Пропала серая кошка, отзовитесь", use_model=False)
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
    assert draft.geo_method in {"fuzzy", "postcode", "geo_matcher", "catalog", "spacy+catalog"}
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
        result = classify_by_rules("Сегодня уникальныймаркеркатастрофы в городе")
        assert result.importance == 1
        assert result.disaster_flag is True
    finally:
        clear_rules_cache()


def test_classify_uses_onnx_when_available() -> None:
    fake = ModelPrediction(
        importance=1,
        disaster_flag=False,
        confidence=0.9,
        method="onnx",
        probs=(0.9, 0.05, 0.05),
    )
    clear_rules_cache()
    try:
        with patch(
            "parser_common.classify.predict_importance_onnx",
            return_value=fake,
        ):
            result = classify_importance("Сегодня мегачп рядом", min_confidence=0.3)
        assert result.method == "onnx"
        assert result.importance == 1
        assert result.disaster_flag is False
    finally:
        clear_rules_cache()


def test_ml_importance_independent_of_disaster_keywords() -> None:
    """Модель говорит 2, keywords ЧС → disaster_flag True при importance 2."""
    fake = ModelPrediction(
        importance=2,
        disaster_flag=False,
        confidence=0.8,
        method="onnx",
        probs=(0.1, 0.8, 0.1),
    )
    clear_rules_cache()
    try:
        with patch(
            "parser_common.classify.predict_importance_onnx",
            return_value=fake,
        ):
            result = classify_importance(
                "жкхавария и эвакуация жителей",
                min_confidence=0.3,
            )
        assert result.method == "onnx"
        assert result.importance == 2
        assert result.disaster_flag is True
    finally:
        clear_rules_cache()


def test_persist_candidate_writes_event(db_session) -> None:
    from address.db.address import AddressRow
    from parser_common import ParserCandidate, persist_candidate

    addr = AddressRow(
        address_text="Москва, улица Persist, д. 1",
        postal_code="101000",
        latitude=Decimal("55.75"),
        longitude=Decimal("37.62"),
    )
    db_session.add(addr)
    db_session.flush()

    event = persist_candidate(
        db_session,
        ParserCandidate(
            raw_text="Отключили воду на Persist до вечера",
            source="neighbors_chat",
            source_msg_id="persist-1",
            address_id=addr.id,
        ),
        geo_matcher=None,
    )
    assert event.id is not None
    assert event.importance == 2
    assert event.disaster_flag is False
    assert event.address_id == addr.id
    assert event.source_msg_id == "persist-1"
