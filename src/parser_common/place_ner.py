"""
Извлечение места из текста → привязка к таблице addresses.

Прототип: spaCy NER (ru) → spans LOC/ORG → StreetCatalog / GeoMatcher.
Без spaCy — эвристический fallback через StreetCatalog.lookup по кускам текста.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from address.geocoding import GeoMatcher
from address.street_catalog import StreetCatalog
from project.logging_setup import get_logger

logger = get_logger(__name__)

# spaCy labels для мест (ru_core_news_*). PER намеренно исключён.
_LOC_LABELS = frozenset({"LOC", "LOCATION", "GPE", "FAC"})


@dataclass(frozen=True, slots=True)
class PlaceHit:
    address_id: int
    geo_by: Literal["city", "street", "home"]
    method: str  # "spacy+catalog" | "catalog" | "geo_matcher"
    span: str | None = None
    score: float = 0.0


@lru_cache(maxsize=1)
def _load_spacy(model_name: str):
    try:
        import spacy
    except ImportError:
        logger.debug("spaCy не установлен — place NER fallback на StreetCatalog")
        return None
    try:
        return spacy.load(model_name)
    except OSError:
        logger.warning(
            "spaCy модель %s не найдена. Установите: python -m spacy download %s",
            model_name,
            model_name,
        )
        return None


def clear_spacy_cache() -> None:
    _load_spacy.cache_clear()


def extract_place_spans(text: str, *, spacy_model: str = "ru_core_news_md") -> list[str]:
    """Вернуть текстовые spans мест (spaCy). Пусто если модели нет."""
    nlp = _load_spacy(spacy_model)
    if nlp is None or not text.strip():
        return []
    doc = nlp(text[:4000])
    spans: list[str] = []
    seen: set[str] = set()
    for ent in doc.ents:
        if ent.label_ not in _LOC_LABELS:
            continue
        span = ent.text.strip()
        key = span.casefold()
        if len(span) < 3 or key in seen:
            continue
        # отсечь слишком общие «Москва»/«Россия» как единственный LOC —
        # оставляем, матчер сам решит city vs street
        seen.add(key)
        spans.append(span)
    return spans


def _geo_by_from_hit(
    *, house: str | None, canonical: str | None
) -> Literal["city", "street", "home"]:
    if house:
        return "home"
    if canonical:
        return "street"
    return "city"


def collect_location_hints(
    text: str,
    *,
    spacy_model: str = "ru_core_news_md",
    use_spacy: bool = True,
) -> list[str]:
    """
    Кандидаты места для StreetCatalog: regex-улицы + spaCy LOC/GPE/FAC.

    spaCy не заменяет каталог — только улучшает recall подсказок.
    Stanford CoreNLP не используем (тяжёлый JVM; spaCy уже в ml-runtime).
    """
    from parser_common.geo_text import extract_street_hints, extract_street_lines

    hints: list[str] = []
    hints.extend(extract_street_hints(text))
    hints.extend(extract_street_lines(text))
    if use_spacy:
        hints.extend(extract_place_spans(text, spacy_model=spacy_model))
    from parser_common.geo_text import filter_moscow_location_hints

    uniq = list(dict.fromkeys(h.strip() for h in hints if h and h.strip()))
    uniq = filter_moscow_location_hints(uniq)
    uniq.sort(key=len, reverse=True)
    return uniq


def resolve_place_to_address(
    text: str,
    *,
    street_catalog: StreetCatalog | None = None,
    geo_matcher: GeoMatcher | None = None,
    spacy_model: str = "ru_core_news_md",
    prefer_spacy: bool = True,
) -> PlaceHit | None:
    """
    Найти address_id по тексту новости/объявления.

    Порядок:
      1) regex+spaCy hints → StreetCatalog
      2) StreetCatalog по всему тексту
      3) GeoMatcher.resolve (fuzzy/postcode), если передан
    """
    if not text.strip():
        return None

    hints = collect_location_hints(text, spacy_model=spacy_model, use_spacy=prefer_spacy)

    if street_catalog is not None and hints:
        hit = street_catalog.lookup_hints(hints)
        if hit is not None:
            spacy_spans = extract_place_spans(text, spacy_model=spacy_model) if prefer_spacy else []
            method = "spacy+catalog" if spacy_spans else "catalog"
            return PlaceHit(
                address_id=hit.address_id,
                geo_by=_geo_by_from_hit(house=hit.house, canonical=hit.canonical),
                method=method,
                span=hit.canonical,
                score=float(hit.score),
            )

    if street_catalog is not None:
        hit = street_catalog.lookup(text[:500])
        if hit is not None:
            return PlaceHit(
                address_id=hit.address_id,
                geo_by=_geo_by_from_hit(house=hit.house, canonical=hit.canonical),
                method="catalog",
                span=hit.canonical,
                score=float(hit.score),
            )
        chunks = [c.strip() for c in text.replace("\n", ",").split(",") if c.strip()]
        hit = street_catalog.lookup_hints(chunks[:20])
        if hit is not None:
            return PlaceHit(
                address_id=hit.address_id,
                geo_by=_geo_by_from_hit(house=hit.house, canonical=hit.canonical),
                method="catalog",
                span=hit.canonical,
                score=float(hit.score),
            )

    if geo_matcher is not None:
        geo = geo_matcher.resolve(text)
        if geo.address_id is not None:
            geo_by: Literal["city", "street", "home"]
            if geo.scope == "address":
                geo_by = "home"
            elif geo.scope == "city":
                geo_by = "city"
            else:
                geo_by = "street"
            return PlaceHit(
                address_id=geo.address_id,
                geo_by=geo_by,
                method="geo_matcher",
                span=geo.address_text,
                score=float(geo.score),
            )

    return None
