"""
Сборка title/body из кандидата.

Не ML и не LLM: либо берём готовые поля (новости/паблики),
либо эвристика по raw_text (чат).
"""

from __future__ import annotations

from parser_common.text_features import collapse_ws

_TITLE_MAX = 120
_BODY_MAX = 4000


def build_title_and_body(
    *,
    raw_text: str,
    title: str | None,
    body: str | None,
) -> tuple[str, str]:
    """
    Если title/body уже есть (RSS/паблик) — нормализуем пробелы (регистр сохраняем).
    Иначе: первая непустая строка → title, остальное → body.
    """
    raw = collapse_ws(raw_text)
    if title and title.strip():
        out_title = collapse_ws(title)[:_TITLE_MAX]
        out_body = collapse_ws(body) if body and body.strip() else raw
        return out_title, (out_body[:_BODY_MAX] or out_title)

    if not raw:
        return "Без названия", ""

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if lines:
        out_title = collapse_ws(lines[0])[:_TITLE_MAX]
        rest = collapse_ws(" ".join(lines[1:])) if len(lines) > 1 else raw
        if rest == out_title:
            rest = raw
        return out_title, rest[:_BODY_MAX]

    return raw[:_TITLE_MAX], raw[:_BODY_MAX]
