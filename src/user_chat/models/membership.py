"""Членство пользователя в чате соседей (гео привязано к чату)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChatMembership:
    """
    Чат, в котором состоит пользователь, и его «дом» на карте.

    Проекция users_chat + chats + addresses для ленты и карты.
    Координаты не хранятся в таблице чатов.
    """

    chat_id: int
    address_id: int
    title: str
    lat: float
    lon: float
    nearby_radius_m: float
    city_radius_m: float
