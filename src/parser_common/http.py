"""Общий HTTP-клиент для парсеров-воркеров."""

from __future__ import annotations

import httpx

from project.logging_setup import get_logger

logger = get_logger(__name__)


def make_http_client(
    *,
    user_agent: str,
    request_timeout_seconds: float,
    max_connections: int = 20,
) -> httpx.AsyncClient:
    # Connect не режем искусственно до 5с: при параллельных outlet-ах DNS/TLS
    # часто дольше, и collect сыпется ConnectTimeout при живых сайтах.
    read_timeout = max(5.0, float(request_timeout_seconds))
    connect_timeout = max(10.0, min(read_timeout, 30.0))
    timeout = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=read_timeout,
        pool=min(10.0, connect_timeout),
    )
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max(4, max_connections // 2),
    )
    return httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    )


async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
    """GET с raise_for_status (логирует ошибку)."""
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
