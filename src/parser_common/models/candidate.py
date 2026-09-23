"""Вход парсерного пайплайна.

Продюсеры:
  - KAN-10 ``parse_chat`` — сообщения соседских чатов
  - KAN-11 ``parse_news`` — RSS / локальные СМИ
  - KAN-12 ``parse_max_public`` — публичные каналы Max (пока нет)
  - KAN-28 ``parse_mc`` — сайты УК / ЖЭК Москвы

Воркер собирает только сырьё в этот DTO, дальше — ``parser_common.normalize`` /
``persist_candidate``. Classify и запись в events внутри парсера не дублировать.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ParserCandidate:
    """
    Кандидат на событие до classify/normalize.

    Новости обычно уже кладут title/body;
    чат — чаще только raw_text (+ опционально geo_text / address_id чата).
    """

    raw_text: str
    source: str
    source_msg_id: str | None = None
    title: str | None = None
    body: str | None = None
    source_url: str | None = None
    image_url: str | None = None
    address_id: int | None = None
    geo_by: str | None = None
    # Текст для геокодинга (если address_id ещё нет). Если None — берём raw_text/title.
    geo_text: str | None = None
    published_at: datetime | None = None
