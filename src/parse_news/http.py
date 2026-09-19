"""HTTP-клиент парсера новостей (settings → AsyncClient)."""

from __future__ import annotations

import httpx

from parser_common.http import make_http_client
from project.config import Settings


def make_client(settings: Settings) -> httpx.AsyncClient:
    cfg = settings.news_parser
    return make_http_client(
        user_agent=cfg.user_agent,
        request_timeout_seconds=float(cfg.request_timeout_seconds),
        max_connections=20,
    )
