"""Сборка title/body из кандидата (без LLM)."""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_TITLE_MAX = 120
_BODY_MAX = 4000


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def build_title_and_body(
    *,
    raw_text: str,
    title: str | None,
    body: str | None,
) -> tuple[str, str]:
    """
    Если title/body уже есть (RSS/паблик) — нормализуем.
    Иначе эвристика по raw_text: первая строка → title, остальное → body.
    """
    raw = _clean(raw_text)
    if title and title.strip():
        out_title = _clean(title)[:_TITLE_MAX]
        out_body = _clean(body) if body and body.strip() else raw
        return out_title, out_body[:_BODY_MAX] or out_title

    if not raw:
        return "Без названия", ""

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if lines:
        out_title = _clean(lines[0])[:_TITLE_MAX]
        rest = _clean(" ".join(lines[1:])) if len(lines) > 1 else raw
        if rest == out_title:
            rest = raw
        return out_title, rest[:_BODY_MAX]

    out_title = raw[:_TITLE_MAX]
    return out_title, raw[:_BODY_MAX]
