"""Чистые функции: вес события, гео и правила ленты/карты."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

# Базовая надёжность канала источника (0..1), если нет per-outlet в конфиге.
SOURCE_RELIABILITY_DEFAULT: dict[str, float] = {
    "neighbors_chat": 0.95,
    "news": 0.70,
    "mc": 0.85,
    "max_public": 0.65,
    "manual": 0.80,
}

# Fallback по outlet (перекрывается news_parser/mc_parser.sources.*.reliability).
OUTLET_RELIABILITY_DEFAULT: dict[str, float] = {
    "tass": 0.92,
    "ria": 0.90,
    "kommersant": 0.88,
    "m24": 0.85,
    "msk1": 0.82,
    "mskagency": 0.80,
    "pik_comfort": 0.88,
    "granel": 0.80,
    "zhil_nagatino": 0.90,
    "gbu_portal": 0.78,
    "moek": 0.92,
}

_IMPORTANCE_RELEVANCE = {1: 1.0, 2: 0.72, 3: 0.42}
_GEO_BY_RELEVANCE = {"home": 1.0, "street": 0.78, "city": 0.48}
_HALF_LIFE_HOURS = 24.0

# Порядок близости для nearby (метры). Дальше — отсев по nearby_radius_m.
PROXIMITY_HOME_M = 250.0
PROXIMITY_BLOCK_M = 800.0
PROXIMITY_STREET_M = 1_500.0

_STREET_PREFIX_RE = re.compile(
    r"^(ул\.?|улица|пр-?т\.?|проспект|пер\.?|переулок|б-?р\.?|бульвар|ш\.?|шоссе)\s+",
    re.IGNORECASE,
)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между двумя WGS84-точками в метрах."""
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_m * math.asin(min(1.0, math.sqrt(a)))


def proximity_band(distance_m: float) -> str:
    """
    Дискретный порядок близости для UI и отладки ранжирования.

    home → block → street → district (в пределах nearby_radius_m).
    """
    if distance_m <= PROXIMITY_HOME_M:
        return "home"
    if distance_m <= PROXIMITY_BLOCK_M:
        return "block"
    if distance_m <= PROXIMITY_STREET_M:
        return "street"
    return "district"


def bbox_delta_degrees(*, lat: float, radius_m: float) -> tuple[float, float]:
    """Полуоси bbox вокруг точки: (Δlat°, Δlon°) для грубого SQL-фильтра."""
    delta_lat = radius_m / 111_320.0
    cos_lat = max(0.2, abs(math.cos(math.radians(lat))))
    delta_lon = radius_m / (111_320.0 * cos_lat)
    return delta_lat, delta_lon


def normalize_street_name(value: str | None) -> str | None:
    """Сравнение улиц чата и события без учёта «ул./проспект»."""
    if value is None:
        return None
    text = " ".join(value.strip().lower().split())
    if not text:
        return None
    text = _STREET_PREFIX_RE.sub("", text).strip(" ,.")
    return text or None


def streets_match(a: str | None, b: str | None) -> bool:
    left = normalize_street_name(a)
    right = normalize_street_name(b)
    return left is not None and left == right


def event_is_active_now(
    *,
    active_from: datetime | None,
    active_to: datetime | None,
    now: datetime | None = None,
) -> bool | None:
    """
    Окно действия события.

    None — окно неизвестно; True — сейчас действует; False — ещё не началось / уже кончилось.
    """
    if active_from is None and active_to is None:
        return None
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)

    start = active_from
    end = active_to
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)

    if start is not None and current < start:
        return False
    return end is None or current <= end


def apply_nearby_boosts(
    weight: float,
    *,
    same_street: bool = False,
    is_active_now: bool | None = None,
) -> float:
    """Локальные бусты только для персональной nearby-ленты (итог в [0, 1])."""
    score = float(weight)
    if same_street:
        score += 0.07
    if is_active_now is True:
        score += 0.05
    elif is_active_now is False:
        score -= 0.08
    return _clamp01(score)


def outlet_from_source_msg_id(source_msg_id: str | None) -> str | None:
    if not source_msg_id or ":" not in source_msg_id:
        return None
    return source_msg_id.split(":", 1)[0].strip() or None


def resolve_source_reliability(
    *,
    source: str,
    source_msg_id: str | None = None,
    outlet_reliability: dict[str, float] | None = None,
) -> float:
    """Надёжность 0..1: outlet из конфига → дефолт outlet → дефолт канала."""
    outlet = outlet_from_source_msg_id(source_msg_id)
    if outlet and outlet_reliability and outlet in outlet_reliability:
        return _clamp01(outlet_reliability[outlet])
    if outlet and outlet in OUTLET_RELIABILITY_DEFAULT:
        return OUTLET_RELIABILITY_DEFAULT[outlet]
    return SOURCE_RELIABILITY_DEFAULT.get(source, 0.5)


def relevance_score(
    *,
    importance: int,
    distance_m: float | None = None,
    geo_by: str | None = None,
) -> float:
    """
    Актуальность для жителя ЖКХ / соседского чата (0..1).

    Важно рядом и с точным адресом — выше; бытовуха далеко — ниже.
    """
    imp = _IMPORTANCE_RELEVANCE.get(importance, 0.3)
    # Без дистанции (запись в БД) — нейтральный mid; в ленте пересчитаем.
    dist = 0.55 if distance_m is None else max(0.0, 1.0 - min(distance_m, 5000.0) / 5000.0)
    geo = _GEO_BY_RELEVANCE.get(geo_by or "", 0.30)
    return _clamp01(0.50 * imp + 0.35 * dist + 0.15 * geo)


def timeliness_score(
    *,
    published_at: datetime | None = None,
    created_at: datetime | None = None,
    now: datetime | None = None,
) -> float:
    """Свежесть 0..1: half-life 24 часа; возраст в целых часах (стабильный cursor)."""
    anchor = published_at or created_at
    if anchor is None:
        return 0.5
    current = now or datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    age_h = max(0, int((current - anchor).total_seconds() // 3600))
    return _clamp01(math.exp(-math.log(2) * age_h / _HALF_LIFE_HOURS))


def compute_weight(
    *,
    importance: int,
    source: str,
    distance_m: float | None = None,
    geo_by: str | None = None,
    published_at: datetime | None = None,
    created_at: datetime | None = None,
    source_msg_id: str | None = None,
    source_reliability: float | None = None,
    outlet_reliability: dict[str, float] | None = None,
    now: datetime | None = None,
) -> float:
    """
    Вес для TikTok-ленты (выше — выше в выдаче)::

        weight = 0.50 × relevance + 0.30 × timeliness + 0.20 × source_reliability

    Все компоненты в [0, 1]; итог тоже в [0, 1].
    """
    if importance not in (1, 2, 3):
        raise ValueError(f"importance должен быть 1..3, получено {importance}")

    relevance = relevance_score(
        importance=importance,
        distance_m=distance_m,
        geo_by=geo_by,
    )
    timeliness = timeliness_score(
        published_at=published_at,
        created_at=created_at,
        now=now,
    )
    reliability = (
        _clamp01(source_reliability)
        if source_reliability is not None
        else resolve_source_reliability(
            source=source,
            source_msg_id=source_msg_id,
            outlet_reliability=outlet_reliability,
        )
    )
    return 0.50 * relevance + 0.30 * timeliness + 0.20 * reliability


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def allowed_in_feed(*, importance: int) -> bool:
    """В лентах (nearby/city) нет бытовухи (importance=3)."""
    return importance in (1, 2)


def matches_feed_geo(*, scope: str, geo_by: str | None) -> bool:
    """Nearby — street|home; city — city. Дистанция/радиус — в list_feed nearby."""
    if geo_by is None:
        return False
    value = geo_by.strip().lower()
    if scope == "nearby":
        return value in ("street", "home")
    if scope == "city":
        return value == "city"
    return False


def allowed_in_city_feed(*, importance: int, disaster_flag: bool) -> bool:
    """Устарело для ленты: см. allowed_in_feed + matches_feed_geo. Оставлено для тестов веса."""
    if importance == 3:
        return False
    if importance == 1:
        return disaster_flag
    return importance == 2


def allowed_on_map(*, importance: int, disaster_flag: bool) -> bool:
    """
    На карте только важное и катастрофы (отключение воды, ЧС).

    Бытовуха (importance=3) и мусор (<=0) — нет.
    disaster_flag усиливает показ importance=1.
    """
    if importance <= 0 or importance >= 3:
        return False
    if importance == 1:
        return True
    return importance == 2 or disaster_flag


def map_icon_category(*, importance: int, disaster_flag: bool) -> str:
    """
    Код категории для иконки в Yandex (конструктор / JS API).

    Клиент мапит строку на конкретную иконку/цвет.
    """
    if disaster_flag or importance == 1:
        return "catastrophe"
    if importance == 2:
        return "important"
    return "minor"
