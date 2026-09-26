"""Инлайн-ссылки на страницы документации (не кнопки клавиатуры)."""

from __future__ import annotations

from html import escape

from project.config import get_settings


def html_link(label: str, url: str) -> str:
    """HTML-ссылка для сообщений с format=HTML."""
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


def md_link(label: str, url: str) -> str:
    """Markdown-ссылка для сообщений с format=markdown."""
    safe_label = label.replace("[", "\\[").replace("]", "\\]")
    return f"[{safe_label}]({url})"


def docs_html(label: str, *, page: str | None = None) -> str:
    docs = get_settings().docs
    url = docs.page(page) if page else docs.url
    return html_link(label, url)


def docs_md(label: str, *, page: str | None = None) -> str:
    docs = get_settings().docs
    url = docs.page(page) if page else docs.url
    return md_link(label, url)
