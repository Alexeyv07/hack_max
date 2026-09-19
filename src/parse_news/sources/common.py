"""Общие хелперы адаптеров новостей → RawNewsArticle (обёртка над parser_common.scrape)."""

from __future__ import annotations

from datetime import datetime

import httpx

from parse_news.models.article import RawNewsArticle
from parser_common.rss import RssItem
from parser_common.scrape import (
    ScrapedPage,
    collect_pages_from_rss,
    enrich_page_from_html,
    ensure_aware,
    extract_id_from_url,
    fetch_optional,
    find_links,
    iter_days_backward,
    page_from_rss,
    parse_datetime,
    parse_ru_date,
    parse_sitemap_entries,
    title_from_slug,
)
from parser_common.scrape import (
    enrich_url as scrape_enrich_url,
)

__all__ = [
    "article_from_rss",
    "collect_from_rss",
    "enrich_from_html",
    "enrich_url",
    "ensure_aware",
    "extract_id_from_url",
    "fetch_optional",
    "find_links",
    "iter_days_backward",
    "parse_datetime",
    "parse_ru_date",
    "parse_sitemap_entries",
    "title_from_slug",
]


def _to_article(page: ScrapedPage, *, outlet: str) -> RawNewsArticle:
    return RawNewsArticle(
        outlet=outlet,
        external_id=page.external_id,
        url=page.url,
        title=page.title,
        published_at=page.published_at,
        body=page.body,
        image_url=page.image_url,
    )


def article_from_rss(
    item: RssItem,
    *,
    outlet: str,
    external_id: str | None = None,
    default_published: datetime | None = None,
) -> RawNewsArticle | None:
    page = page_from_rss(item, external_id=external_id, default_published=default_published)
    if page is None:
        return None
    return _to_article(page, outlet=outlet)


def enrich_from_html(
    html: str,
    *,
    outlet: str,
    url: str,
    external_id: str,
    fallback_title: str | None = None,
    fallback_body: str | None = None,
    fallback_published: datetime | None = None,
) -> RawNewsArticle:
    page = enrich_page_from_html(
        html,
        url=url,
        external_id=external_id,
        fallback_title=fallback_title,
        fallback_body=fallback_body,
        fallback_published=fallback_published,
    )
    return _to_article(page, outlet=outlet)


async def enrich_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    outlet: str,
    external_id: str,
    fallback_title: str | None = None,
    fallback_published: datetime | None = None,
) -> RawNewsArticle | None:
    page = await scrape_enrich_url(
        client,
        url,
        external_id=external_id,
        fallback_title=fallback_title,
        fallback_published=fallback_published,
    )
    if page is None:
        return None
    return _to_article(page, outlet=outlet)


async def collect_from_rss(
    client: httpx.AsyncClient,
    feed_url: str,
    *,
    outlet: str,
    since: datetime,
    max_articles: int,
) -> list[RawNewsArticle]:
    pages = await collect_pages_from_rss(client, feed_url, since=since, max_articles=max_articles)
    return [_to_article(page, outlet=outlet) for page in pages]
