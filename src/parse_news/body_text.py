"""Очистка body новости от заглушек вроде «Подробнее на сайте»."""

from __future__ import annotations

import re

from parser_common.text_features import collapse_ws

# Целиком заглушка (og:description Коммерсанта и т.п.).
_BOILERPLATE_ONLY = re.compile(
    r"(?is)^\s*(?:"
    r"подробнее(?:\s+на\s+сайте)?|"
    r"читать\s+далее|"
    r"читайте\s+(?:также|далее)|"
    r"материал\s+предоставлен|"
    r"подписывайтесь|"
    r"источник\s*:?\s*"
    r")\s*[.!]?\s*$"
)

# Хвост в конце реального текста.
_BOILERPLATE_SUFFIX = re.compile(
    r"(?is)\s*(?:"
    r"подробнее(?:\s+на\s+сайте)?|"
    r"читать\s+далее|"
    r"читайте\s+(?:также|далее)"
    r")\s*[.!]?\s*$"
)

_MIN_SUBSTANTIVE_LEN = 48


def is_boilerplate_body(text: str | None) -> bool:
    if not text or not text.strip():
        return True
    cleaned = collapse_ws(text)
    if _BOILERPLATE_ONLY.match(cleaned):
        return True
    low = cleaned.lower()
    return len(cleaned) < _MIN_SUBSTANTIVE_LEN and (
        "подробнее" in low or "читать далее" in low or "читайте" in low
    )


def clean_article_body(text: str | None, *, title: str | None = None) -> str | None:
    """Вернуть содержательный body или None, если текста нет / только заглушка."""
    if not text:
        return None
    cleaned = collapse_ws(text)
    cleaned = _BOILERPLATE_SUFFIX.sub("", cleaned).strip(" .-—–")
    if not cleaned or is_boilerplate_body(cleaned):
        return None

    if title:
        title_n = collapse_ws(title)
        if title_n and cleaned.lower().startswith(title_n.lower()):
            rest = cleaned[len(title_n) :].lstrip(" .:—–-")
            if rest and not is_boilerplate_body(rest):
                cleaned = rest
            elif rest == "" or is_boilerplate_body(rest):
                # Body = title (+ заглушка) — не дублируем заголовок как «содержание».
                return None

    if len(cleaned) < 20:
        return None
    return cleaned
