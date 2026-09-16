"""Членство пользователя в чате соседей (гео привязано к чату)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChatMembership:
    """
    Чат, в котором состоит пользователь, и его «дом» на карте.

    Позже придёт из таблицы users_chat + address (KAN-5 / KAN-6).
    """

    chat_id: int
    title: str
    lat: float
    lon: float
    nearby_radius_m: float
    city_radius_m: float
