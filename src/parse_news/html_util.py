"""BeautifulSoup-хелперы для HTML-источников новостей."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_TAG = re.compile(r"<[^>]+>")


def soup_from(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def absolute_url(base: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href:
        return None
    return urljoin(base, href)


def meta_content(soup: BeautifulSoup, *names_or_props: str) -> str | None:
    for name in names_or_props:
        tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        if tag and tag.get("content"):
            value = str(tag["content"]).strip()
            if value:
                return value
    return None


def first_text(soup: BeautifulSoup, *css_selectors: str) -> str | None:
    for selector in css_selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        text = node.get_text(" ", strip=True)
        if text:
            return text
    return None


def join_paragraphs(soup: BeautifulSoup, *css_selectors: str, limit: int = 12) -> str | None:
    """Склеить <p> внутри первого подходящего контейнера (содержательный body)."""
    for selector in css_selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        parts: list[str] = []
        for p in node.find_all("p"):
            chunk = p.get_text(" ", strip=True)
            if chunk:
                parts.append(chunk)
            if len(parts) >= limit:
                break
        if parts:
            return " ".join(parts)
        text = node.get_text(" ", strip=True)
        if text:
            return text
    return None


def strip_html(html_or_text: str | None) -> str:
    if not html_or_text:
        return ""
    if "<" not in html_or_text:
        return html_or_text.strip()
    soup = soup_from(html_or_text)
    return soup.get_text(" ", strip=True)
