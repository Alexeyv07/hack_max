"""HTTP-клиент для загрузки RSS и HTML страниц источников."""

from __future__ import annotations

import httpx

from project.config import Settings
from project.logging_setup import get_logger

logger = get_logger(__name__)


def make_client(settings: Settings) -> httpx.AsyncClient:
    cfg = settings.news_parser
    timeout = httpx.Timeout(
        connect=min(5.0, float(cfg.request_timeout_seconds)),
        read=float(cfg.request_timeout_seconds),
        write=float(cfg.request_timeout_seconds),
        pool=5.0,
    )
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    return httpx.AsyncClient(
        headers={"User-Agent": cfg.user_agent},
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    )


async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "HTTP %s при загрузке %s: %s",
            exc.response.status_code,
            url,
            exc.response.text[:200],
        )
        raise
    except httpx.HTTPError as exc:
        logger.error("Ошибка сети при загрузке %s: %s", url, exc)
        raise
    return response.text
