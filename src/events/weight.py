"""Чистые функции: вес события, гео и правила ленты/карты."""

from __future__ import annotations

import math

# Бонус источника к весу (чем выше — тем заметнее в ленте).
SOURCE_BONUS: dict[str, float] = {
    "neighbors_chat": 30.0,
    "news": 20.0,
    "max_public": 10.0,
    "manual": 15.0,
}

# Шкала importance в продукте:
#   1 — катастрофа / наивысший приоритет
#   2 — важное городское (отключили воду в районе, …)
#   3 — бытовуха / шум (пропала кошка, бельё на верёвке, …) — не на карту
#   0 и ниже — мусор, не используем


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между двумя WGS84-точками в метрах."""
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_m * math.asin(min(1.0, math.sqrt(a)))


def compute_weight(
    *,
    importance: int,
    source: str,
    distance_m: float | None = None,
) -> float:
    """
    Вес для сортировки ленты.

    importance 1 — самый важный → больший вклад.
    Ближе к пользователю — чуть выше вес.
    """
    if importance not in (1, 2, 3):
        raise ValueError(f"importance должен быть 1..3, получено {importance}")

    importance_score = (4 - importance) * 100.0
    source_score = SOURCE_BONUS.get(source, 0.0)

    if distance_m is None:
        distance_score = 0.0
    else:
        # Линейный спад: 0 м → +50, 5000 м → 0, дальше 0.
        distance_score = max(0.0, 50.0 * (1.0 - min(distance_m, 5000.0) / 5000.0))

    return importance_score + source_score + distance_score


def allowed_in_city_feed(*, importance: int, disaster_flag: bool) -> bool:
    """В городской ленте importance=1 только при disaster_flag."""
    if importance == 1:
        return disaster_flag
    return importance in (2, 3)


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
