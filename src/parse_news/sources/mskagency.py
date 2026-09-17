"""Адаптер mskagency.ru (HTML lenta: data-datei + page pagination)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, time

import httpx

from parse_news.html_util import soup_from
from parse_news.http import fetch_text
from parse_news.models.article import RawNewsArticle
from parse_news.sources.base import BaseNewsSource, CollectMode, CollectResult
from parse_news.sources.common import enrich_from_html, ensure_aware, fetch_optional
from project.config import NewsSourceConfig
from project.logging_setup import get_logger

logger = get_logger(__name__)

_DEFAULT_LISTING = "https://www.mskagency.ru/lenta"
_MATERIAL_URL = "https://www.mskagency.ru/materials/{material_id}"
_TITLE_RE = re.compile(
    r'<a href="/materials/(?P<id>\d+)"[^>]*title="(?P<title>[^"]*)"',
    re.I,
)


class MskagencySource(BaseNewsSource):
    key = "mskagency"

    def __init__(self, cfg: NewsSourceConfig | None = None) -> None:
        self.cfg = cfg or NewsSourceConfig()

    async def collect(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        mode: CollectMode,
        listing_cursor: str | None,
        max_articles: int,
    ) -> CollectResult:
        start_page = 1
        max_pages = 1 if mode == "incremental" else None
        if mode == "backfill" and listing_cursor and listing_cursor.isdigit():
            start_page = max(1, int(listing_cursor))
        return await self._collect_pages(
            client,
            since=since,
            start_page=start_page,
            max_articles=max_articles,
            max_pages=max_pages,
        )

    async def _collect_pages(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime,
        start_page: int,
        max_articles: int,
        max_pages: int | None,
    ) -> CollectResult:
        listing_url = self.cfg.listing_url or _DEFAULT_LISTING
        articles: list[RawNewsArticle] = []
        reached_since = False
        page = start_page
        pages_done = 0
        next_cursor: str | None = None
        empty_pages = 0

        while len(articles) < max_articles:
            if max_pages is not None and pages_done >= max_pages:
                break

            url = listing_url if page <= 1 else f"{listing_url}?page={page}"
            try:
                html = await fetch_text(client, url)
            except httpx.HTTPError as exc:
                logger.error("mskagency listing %s: %s", url, exc)
                if pages_done == 0:
                    raise
                break

            rows = parse_lenta_rows(html)
            pages_done += 1
            if not rows:
                empty_pages += 1
                if empty_pages >= 2:
                    reached_since = True
                    break
                page += 1
                continue
            empty_pages = 0

            page_hit_cap = False
            for material_id, published, title in rows:
                if published < since:
                    reached_since = True
                    continue
                if len(articles) >= max_articles:
                    page_hit_cap = True
                    next_cursor = str(page)
                    break
                article = await self._fetch_article(
                    client,
                    material_id=material_id,
                    published=published,
                    title=title,
                )
                if article is not None:
                    articles.append(article)

            if page_hit_cap or reached_since:
                break

            page += 1

        if next_cursor is None and not reached_since and max_pages is None:
            if len(articles) >= max_articles:
                next_cursor = str(page)
            else:
                reached_since = True

        articles.sort(key=lambda a: a.published_at, reverse=True)
        return CollectResult(
            articles=_dedupe(articles),
            next_cursor=next_cursor,
            reached_since=reached_since,
        )

    async def _fetch_article(
        self,
        client: httpx.AsyncClient,
        *,
        material_id: int,
        published: datetime,
        title: str | None,
    ) -> RawNewsArticle | None:
        url = _MATERIAL_URL.format(material_id=material_id)
        status, page = await fetch_optional(client, url)
        published_aware = ensure_aware(published) or datetime.now(UTC)
        if status == 200 and page:
            article = enrich_from_html(
                page,
                outlet=self.key,
                url=url,
                external_id=str(material_id),
                fallback_title=title,
                fallback_published=published_aware,
            )
            return RawNewsArticle(
                outlet=article.outlet,
                external_id=article.external_id,
                url=article.url,
                title=article.title,
                published_at=published_aware,
                body=article.body,
                image_url=article.image_url,
            )
        return RawNewsArticle(
            outlet=self.key,
            external_id=str(material_id),
            url=url,
            title=title or str(material_id),
            published_at=published_aware,
            body=None,
        )


def parse_lenta_rows(html: str) -> list[tuple[int, datetime, str | None]]:
    titles = {int(m.group("id")): _unescape(m.group("title")) for m in _TITLE_RE.finditer(html)}
    rows: list[tuple[int, datetime, str | None]] = []
    soup = soup_from(html)
    for li in soup.select("li[data-material_id][data-datei]"):
        mid_raw = li.get("data-material_id")
        datei = li.get("data-datei")
        if not mid_raw or not datei:
            continue
        hm = "00:00"
        time_el = li.select_one("div.time")
        if time_el is not None:
            m_hm = re.search(r"(\d{1,2}:\d{2})", time_el.get_text(" ", strip=True))
            if m_hm:
                hm = m_hm.group(1)
        try:
            material_id = int(str(mid_raw))
            day = datetime.strptime(str(datei), "%Y%m%d").date()
            hour, minute = map(int, hm.split(":"))
            published = datetime.combine(day, time(hour, minute), tzinfo=UTC)
        except ValueError:
            continue
        rows.append((material_id, published, titles.get(material_id)))
    return rows


def _unescape(value: str) -> str:
    return value.replace("&quot;", '"').replace("&amp;", "&").replace("&#39;", "'").strip()


def _dedupe(articles: list[RawNewsArticle]) -> list[RawNewsArticle]:
    seen: set[str] = set()
    out: list[RawNewsArticle] = []
    for article in articles:
        if article.external_id in seen:
            continue
        seen.add(article.external_id)
        out.append(article)
    return out
