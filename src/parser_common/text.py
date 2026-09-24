"""Сборка title/body из кандидата.

Не ML и не LLM: либо берём готовые поля (новости/паблики),
либо эвристика по raw_text (чат).

Title необязателен: если заголовок не извлечь или он совпадает с телом —
возвращаем title=None (в UI показывается body).
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
) -> tuple[str | None, str]:
    """
    Если title/body уже есть (RSS/паблик) — нормализуем пробелы (регистр сохраняем).
    Иначе: первая непустая строка → title, остальное → body.
    Не дублируем title в body (раньше пустой body = title → карточки «равны»).
    """
    raw = collapse_ws(raw_text)
    provided_title = collapse_ws(title)[:_TITLE_MAX] if title and title.strip() else None
    provided_body = collapse_ws(body)[:_BODY_MAX] if body and body.strip() else None

    if provided_title is not None:
        out_body = provided_body or raw
        if out_body and _same_text(provided_title, out_body):
            # Один и тот же текст — оставляем только body, без фейкового заголовка.
            return None, out_body[:_BODY_MAX]
        return provided_title, (out_body or "")[:_BODY_MAX]

    if not raw:
        return None, ""

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if len(lines) >= 2:
        out_title = collapse_ws(lines[0])[:_TITLE_MAX]
        rest = collapse_ws(" ".join(lines[1:]))[:_BODY_MAX]
        if rest and not _same_text(out_title, rest):
            return out_title, rest
        return None, raw[:_BODY_MAX]

    # Одна строка / сплошной текст — заголовка нет, весь текст в body.
    return None, raw[:_BODY_MAX]


def _same_text(a: str, b: str) -> bool:
    return collapse_ws(a).casefold() == collapse_ws(b).casefold()
