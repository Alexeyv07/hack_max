"""Тесты parser_common: classify + normalize + model infer."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from address.geocoding import GeoMatcher
from address.models.address import Address
from events.models.event import EventCreate
from parser_common import EventDraft, ParserCandidate, normalize, to_event_create
from parser_common.classify import (
    classify_by_rules,
    classify_importance,
    clear_rules_cache,
)
from parser_common.model_infer import clear_model_cache, predict_importance


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
        result = classify_by_rules("Сегодня уникальныймаркеркатастрофы в городе")
        assert result.importance == 1
        assert result.disaster_flag is True
    finally:
        clear_rules_cache()


def _write_tiny_model(path: Path) -> None:
    """Минимальный артефакт: маркеры вне keyword-rules."""
    vocab = {"мегачп": 0, "жкхавария": 1, "бытовухамаркер": 2}
    idf = [1.0, 1.0, 1.0]
    coef = [
        [5.0, 0.0, 0.0],
        [0.0, 5.0, 0.0],
        [0.0, 0.0, 5.0],
    ]
    payload = {
        "format": "tfidf_logreg_v1",
        "ngram_range": [1, 1],
        "analyzer": "word",
        "vocabulary": vocab,
        "idf": idf,
        "classes": [1, 2, 3],
        "coef": coef,
        "intercept": [0.0, 0.0, 0.0],
        "disaster_is_importance_1": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_model_infer_predicts(tmp_path, monkeypatch) -> None:
    model = tmp_path / "m.json"
    _write_tiny_model(model)
    clear_model_cache()
    try:
        pred = predict_importance("Сегодня мегачп в городе", path=model, min_confidence=0.3)
        assert pred is not None
        assert pred.importance == 1
        assert pred.disaster_flag is False

        pred2 = predict_importance("Большая жкхавария на сети", path=model, min_confidence=0.3)
        assert pred2 is not None
        assert pred2.importance == 2

        pred3 = predict_importance("Просто бытовухамаркер во дворе", path=model, min_confidence=0.3)
        assert pred3 is not None
        assert pred3.importance == 3
    finally:
        clear_model_cache()


def test_classify_uses_model_when_available(tmp_path, monkeypatch) -> None:
    model = tmp_path / "m.json"
    _write_tiny_model(model)
    monkeypatch.setattr(
        "parser_common.model_infer.DEFAULT_MODEL_PATH",
        model,
    )
    clear_rules_cache()
    try:
        # Нет keyword-совпадений → rules дали бы 3; модель поднимает importance до 1.
        # disaster_flag при этом False (нет ЧС-keywords).
        result = classify_importance("Сегодня мегачп рядом", min_confidence=0.3)
        assert result.method == "tfidf"
        assert result.importance == 1
        assert result.disaster_flag is False
    finally:
        clear_rules_cache()


def test_ml_importance_independent_of_disaster_keywords(tmp_path, monkeypatch) -> None:
    """Модель говорит 2, keywords ЧС → disaster_flag True при importance 2."""
    model = tmp_path / "m.json"
    _write_tiny_model(model)
    monkeypatch.setattr("parser_common.model_infer.DEFAULT_MODEL_PATH", model)
    clear_rules_cache()
    try:
        result = classify_importance(
            "жкхавария и эвакуация жителей",
            min_confidence=0.3,
        )
        assert result.method == "tfidf"
        assert result.importance == 2
        assert result.disaster_flag is True
    finally:
        clear_rules_cache()
