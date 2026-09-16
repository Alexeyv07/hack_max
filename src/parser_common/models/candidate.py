"""Вход парсерного пайплайна (сырьё от parse_chat / parse_news / parse_max_public)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParserCandidate:
    """
    Кандидат на событие до classify/normalize.

    Парсеры новостей обычно уже кладут title/body;
    чат — чаще только raw_text (+ опционально geo_text).
    """

    raw_text: str
    source: str
    source_msg_id: str | None = None
    title: str | None = None
    body: str | None = None
    source_url: str | None = None
    image_url: str | None = None
    address_id: int | None = None
    # Текст для геокодинга (если address_id ещё нет). Если None — берём raw_text/title.
    geo_text: str | None = None
