"""Тонкий LLM-клиент (AITunnel) для суммаризации сообщений домового чата."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Sequence

import httpx

from notify.chat_source import ChatMessage
from project.config import NotifyConfig, get_settings
from project.logging_setup import get_logger

logger = get_logger(__name__)

_AITUNNEL_URL = "https://api.aitunnel.ru/v1/chat/completions"
_DEFAULT_MODEL = "deepseek-v4-flash-0731"

_SYSTEM_PROMPT = (
    "Ты составляешь короткое резюме переписки соседей одного дома. "
    "Верни только 3–5 коротких буллетов на русском языке, без вступления. "
    "Объединяй повторяющиеся мысли и оставляй факты, решения, проблемы и важные вопросы. "
    "Используй только факты из переданных сообщений и ничего не придумывай."
)

_BULLET_RE = re.compile(r"^\s*(?:[-*•–—]|\d+[.)])\s*(.+?)\s*$")


async def summarize_digest(
    messages: Sequence[ChatMessage],
    *,
    config: NotifyConfig | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str | None:
    """Суммаризировать тексты сообщений; при любой проблеме вернуть ``None`` для fallback."""
    if not messages:
        return None

    cfg = config or get_settings().notify
    request = _build_request(cfg, messages=messages)
    if request is None:
        return None

    attempts = max(1, int(cfg.summarizer_retry_count) + 1)
    timeout = max(1.0, float(cfg.summarizer_timeout_seconds))

    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.post(
                    request.url,
                    headers=request.headers,
                    json=request.payload,
                )
                response.raise_for_status()
                content = _extract_content(response.json())
                digest = _normalize_digest(content)
                if digest is not None:
                    return digest
                logger.warning("Summarizer вернул ответ не в формате 3–5 буллетов")
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                logger.warning(
                    "Ошибка AITunnel summarizer attempt=%s/%s",
                    attempt,
                    attempts,
                    exc_info=True,
                )

            if attempt < attempts:
                await asyncio.sleep(0.25)

    return None


class _Request:
    __slots__ = ("headers", "payload", "url")

    def __init__(self, *, url: str, headers: dict[str, str], payload: dict[str, object]):
        self.url = url
        self.headers = headers
        self.payload = payload


def _build_request(cfg: NotifyConfig, *, messages: Sequence[ChatMessage]) -> _Request | None:
    api_key = os.getenv("AITUNNEL_API_KEY", "").strip()
    if not api_key:
        logger.warning("AITUNNEL_API_KEY не задан — суммаризация пропущена")
        return None

    model = (cfg.summarizer_model or "").strip() or _DEFAULT_MODEL
    return _Request(
        url=_AITUNNEL_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        payload={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _messages_prompt(messages)},
            ],
            "temperature": 0.2,
            "max_tokens": 1000,
            "reasoning": {"effort": "minimal", "exclude": True},
            "stream": False,
        },
    )


def _messages_prompt(messages: Sequence[ChatMessage]) -> str:
    # В LLM не передаём Event, chat_id, user_id, importance, адреса и другие метаданные.
    return "\n".join(f"- {message.text}" for message in messages)


def _extract_content(payload: object) -> str:
    if not isinstance(payload, dict):
        raise TypeError("Ответ summarizer должен быть JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("В ответе summarizer нет choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise TypeError("choices[0] должен быть object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise TypeError("В choices[0] нет message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Пустой content от summarizer")
    return content


def _normalize_digest(content: str) -> str | None:
    bullets: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            continue
        match = _BULLET_RE.match(line)
        if match is None:
            continue
        item = " ".join(match.group(1).split())
        if item:
            bullets.append(item)
        if len(bullets) == 5:
            break

    if len(bullets) < 3:
        return None
    return "\n".join(f"• {item}" for item in bullets)
