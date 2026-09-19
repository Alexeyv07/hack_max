"""Общий scrape-слой для парсеров (без доменных Raw* моделей)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from parser_common.body_text import clean_article_body
from parser_common.html_util import (
    absolute_url,
    first_text,
    join_paragraphs,
    meta_content,
    soup_from,
)
from parser_common.http import fetch_text
from parser_common.rss import RssItem, parse_rss

_ISO_DT = re.compile(
    r"(?P<dt>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)

ARTICLE_BODY_SELECTORS = (
    ".doc__text",
    ".doc__body",
    ".article_text_wrapper",
    ".article__text",
    ".article_text",
    ".b-article__text",
    ".news-item__text",
    ".js-mediator-article",
    "[itemprop=articleBody]",
    ".material-text",
    ".article__content",
    ".content__text",
    ".news-detail",
    ".itemFullText",
    ".post-content",
    "article",
    ".content",
)


@dataclass(frozen=True, slots=True)
class ScrapedPage:
    """Распарсенная HTML/RSS-страница до доменной модели воркера."""

    url: str
    external_id: str
    title: str
    published_at: datetime
    body: str | None = None
    image_url: str | None = None


def ensure_aware(dt: datetime | None, *, default: datetime | None = None) -> datetime | None:
    if dt is None:
        return default
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value.replace(" ", "T", 1))
        return ensure_aware(dt)
    except ValueError:
        pass
    try:
        return ensure_aware(parsedate_to_datetime(value))
    except (TypeError, ValueError, IndexError):
        return None


def parse_ru_date(raw: str | None) -> datetime | None:
    """ДД.ММ.ГГГГ[ ЧЧ:ММ] или ISO."""
    if not raw:
        return None
    text = raw.strip()
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour = int(m.group(4) or 0)
        minute = int(m.group(5) or 0)
        return datetime(year, month, day, hour, minute, tzinfo=UTC)
    return parse_datetime(text)


def extract_id_from_url(url: str) -> str | None:
    cleaned = url.split("?", 1)[0].split("#", 1)[0]
    for pattern in (
        r"/doc/(\d+)",
        r"/materials/(\d+)",
        r"/news/\d{8}/(\d+)",
        r"/text/[^/]+/\d{4}/\d{2}/\d{2}/(\d+)/?",
        r"/(\d{5,})/?$",
        r"-(\d{6,})\.html?",
        r"/(\d{6,})\.html?",
        r"[?&]id=(\d+)",
    ):
        m = re.search(pattern, cleaned)
        if m:
            return m.group(1)
    return None


def stable_id(*parts: str, length: int = 16) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:length]


def title_from_slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    slug = re.sub(r"-\d{6,}$", "", slug)
    slug = re.sub(r"^\d+$", "", slug)
    title = slug.replace("-", " ").strip()
    return title or path.rsplit("/", 1)[-1] or url


def iter_days_backward(start: date, since: date) -> list[date]:
    days: list[date] = []
    current = start
    while current >= since:
        days.append(current)
        current -= timedelta(days=1)
    return days


def parse_sitemap_entries(xml_text: str) -> list[tuple[str, datetime | None]]:
    root = ET.fromstring(xml_text)
    entries: list[tuple[str, datetime | None]] = []
    for url_el in root.iter():
        if url_el.tag.rsplit("}", 1)[-1] != "url":
            continue
        loc: str | None = None
        lastmod: datetime | None = None
        for child in url_el:
            local = child.tag.rsplit("}", 1)[-1]
            if local == "loc" and child.text:
                loc = child.text.strip()
            elif local == "lastmod" and child.text:
                lastmod = parse_datetime(child.text.strip())
        if loc:
            entries.append((loc, lastmod))
    entries.sort(key=lambda item: item[1] or datetime.min.replace(tzinfo=UTC), reverse=True)
    return entries


def find_links(
    html: str,
    *,
    base_url: str,
    href_pattern: re.Pattern[str],
) -> list[tuple[str, str | None]]:
    soup = soup_from(html)
    seen: set[str] = set()
    out: list[tuple[str, str | None]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href_pattern.search(href):
            continue
        url = absolute_url(base_url, href)
        if not url or url in seen:
            continue
        seen.add(url)
        text = anchor.get_text(" ", strip=True) or None
        out.append((url, text))
    return out


async def fetch_optional(client: httpx.AsyncClient, url: str) -> tuple[int, str | None]:
    try:
        response = await client.get(url)
    except httpx.HTTPError:
        return 0, None
    if response.status_code >= 400:
        return response.status_code, None
    return response.status_code, response.text


def _json_ld_date(soup: BeautifulSoup) -> datetime | None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string or script.get_text() or ""
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', text)
        if m:
            dt = parse_datetime(m.group(1))
            if dt:
                return dt
        m = _ISO_DT.search(text)
        if m:
            dt = parse_datetime(m.group("dt"))
            if dt:
                return dt
    return None


def enrich_page_from_html(
    html: str,
    *,
    url: str,
    external_id: str,
    fallback_title: str | None = None,
    fallback_body: str | None = None,
    fallback_published: datetime | None = None,
    body_selectors: tuple[str, ...] = ARTICLE_BODY_SELECTORS,
) -> ScrapedPage:
    soup = soup_from(html)
    title = (
        meta_content(soup, "og:title", "twitter:title")
        or first_text(soup, "h1", "h2")
        or fallback_title
        or ""
    )
    title = title.strip() or (fallback_title or url)

    body = clean_article_body(
        join_paragraphs(soup, *body_selectors) or first_text(soup, *body_selectors),
        title=title,
    )
    if body is None:
        body = clean_article_body(
            meta_content(soup, "og:description", "description", "twitter:description"),
            title=title,
        )
    if body is None:
        body = clean_article_body(fallback_body, title=title)

    image = meta_content(soup, "og:image", "twitter:image")
    published = (
        parse_datetime(meta_content(soup, "article:published_time", "pubdate", "publish_date"))
        or _json_ld_date(soup)
        or parse_ru_date(first_text(soup, "time", ".date", ".article__date", ".news-date"))
        or fallback_published
        or datetime.now(UTC)
    )
    return ScrapedPage(
        url=url,
        external_id=external_id,
        title=title,
        published_at=ensure_aware(published) or datetime.now(UTC),
        body=body,
        image_url=image,
    )


async def enrich_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    external_id: str,
    fallback_title: str | None = None,
    fallback_published: datetime | None = None,
) -> ScrapedPage | None:
    status, html = await fetch_optional(client, url)
    if status != 200 or not html:
        return None
    return enrich_page_from_html(
        html,
        url=url,
        external_id=external_id,
        fallback_title=fallback_title,
        fallback_published=fallback_published,
    )


def page_from_rss(
    item: RssItem,
    *,
    external_id: str | None = None,
    default_published: datetime | None = None,
) -> ScrapedPage | None:
    ext = external_id or extract_id_from_url(item.link)
    if not ext and item.guid:
        ext = extract_id_from_url(item.guid) or (
            item.guid if "://" not in item.guid and len(item.guid) <= 64 else None
        )
    if not ext:
        ext = extract_id_from_url(item.link.rstrip("/"))
    if not ext or not item.title:
        return None
    title = item.title.strip()
    body = clean_article_body(item.description, title=title)
    published = ensure_aware(item.published_at) or default_published or datetime.now(UTC)
    return ScrapedPage(
        url=item.link,
        external_id=str(ext)[:96],
        title=title,
        published_at=published,
        body=body,
        image_url=item.image_url,
    )


async def collect_pages_from_rss(
    client: httpx.AsyncClient,
    feed_url: str,
    *,
    since: datetime,
    max_articles: int,
) -> list[ScrapedPage]:
    xml_text = await fetch_text(client, feed_url)
    items = parse_rss(xml_text)
    pages: list[ScrapedPage] = []
    for item in items:
        if len(pages) >= max_articles:
            break
        page = page_from_rss(item)
        if page is None:
            continue
        published = ensure_aware(page.published_at)
        if published and published < since:
            continue
        pages.append(page)
    return pages
