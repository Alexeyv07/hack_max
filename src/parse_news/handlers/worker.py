"""Оркестратор парсера новостей (бесконечный poll-цикл)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from events.handlers.crud import list_existing_source_msg_ids
from events.models.event import EventSource
from parse_news.handlers.geo import MoscowStreetIndex, resolve_article_address
from parse_news.handlers.ingest import persist_article
from parse_news.handlers.state import (
    count_events_for_outlet,
    get_or_create_cursor,
    update_cursor,
)
from parse_news.http import make_client
from parse_news.models.article import RawNewsArticle
from parse_news.registry import get_sources
from parse_news.sources.base import CollectMode, CollectResult, NewsSource
from project.config import NewsParserConfig, get_settings
from project.database import session_scope
from project.logging_setup import get_logger

logger = get_logger(__name__)


def _need_backfill(*, backfill_complete: bool, outlet_event_count: int) -> bool:
    return (not backfill_complete) or outlet_event_count == 0


def _backfill_done_after_collect(
    *,
    previous_complete: bool,
    mode: CollectMode,
    result: CollectResult,
    max_articles: int,
) -> bool:
    """
    backfill_complete только когда реально дошли до lookback.

    Если за прогон набрали ровно max_articles — это лимит пачки, не конец истории.
    """
    if previous_complete and mode != "backfill":
        return True
    if mode != "backfill":
        return previous_complete
    if result.reached_since:
        return True
    # Упёрлись в лимит пачки → продолжим в следующем прогоне.
    if len(result.articles) >= max_articles:
        return False
    # Мало статей и нет курсора — архив исчерпан (или источник пуст после since).
    return result.next_cursor is None


async def _process_source(
    client: httpx.AsyncClient,
    source: NewsSource,
    cfg: NewsParserConfig,
    *,
    street_index: MoscowStreetIndex | None,
) -> bool:
    """
    Один прогон источника. Возвращает True, если backfill ещё не завершён
    (нужен ещё один collect без долгого sleep).
    """
    source_key = source.key
    logger.info("Запуск источника %s", source_key)

    with session_scope() as session:
        cursor = get_or_create_cursor(session, source_key)
        outlet_count = count_events_for_outlet(session, source_key)
        need_backfill = _need_backfill(
            backfill_complete=cursor.backfill_complete,
            outlet_event_count=outlet_count,
        )
        mode: CollectMode = "backfill" if need_backfill else "incremental"
        listing_cursor = cursor.listing_cursor
        previous_complete = cursor.backfill_complete

    since = datetime.now(UTC) - timedelta(days=cfg.lookback_days)
    logger.info(
        "Источник %s: mode=%s since=%s cursor=%s max_per_run=%d",
        source_key,
        mode,
        since.date().isoformat(),
        listing_cursor,
        cfg.max_articles_per_source_per_run,
    )

    try:
        result = await source.collect(
            client,
            since=since,
            mode=mode,
            listing_cursor=listing_cursor,
            max_articles=cfg.max_articles_per_source_per_run,
        )
    except NotImplementedError:
        logger.warning("Адаптер %s ещё не реализован — пропуск", source_key)
        with session_scope() as session:
            cursor = get_or_create_cursor(session, source_key)
            update_cursor(
                session,
                cursor,
                last_run_at=datetime.now(UTC),
                last_error="NotImplementedError: адаптер не реализован",
            )
        return False
    except Exception as exc:
        logger.exception("Ошибка collect для %s: %s", source_key, exc)
        with session_scope() as session:
            cursor = get_or_create_cursor(session, source_key)
            update_cursor(
                session,
                cursor,
                last_run_at=datetime.now(UTC),
                last_error=str(exc),
            )
        return False

    created, skipped, oldest_at, newest_at = _persist_articles_batched(
        result.articles,
        cfg=cfg,
        mode=mode,
        source_key=source_key,
        street_index=street_index,
    )

    backfill_done = _backfill_done_after_collect(
        previous_complete=previous_complete,
        mode=mode,
        result=result,
        max_articles=cfg.max_articles_per_source_per_run,
    )
    # Если упёрлись в лимит, а курсора нет — сохраняем listing_cursor как был,
    # чтобы не потерять прогресс; иначе пишем next_cursor.
    if mode == "backfill" and not backfill_done:
        new_cursor = result.next_cursor if result.next_cursor is not None else listing_cursor
    else:
        new_cursor = None if backfill_done else result.next_cursor

    with session_scope() as session:
        cursor = get_or_create_cursor(session, source_key)
        cursor.listing_cursor = new_cursor
        update_cursor(
            session,
            cursor,
            backfill_complete=backfill_done,
            oldest_seen_at=oldest_at,
            newest_seen_at=newest_at,
            last_run_at=datetime.now(UTC),
            clear_error=True,
        )

    logger.info(
        "Источник %s: создано=%d пропущено=%d fetched=%d backfill_complete=%s next_cursor=%s",
        source_key,
        created,
        skipped,
        len(result.articles),
        backfill_done,
        new_cursor,
    )
    return mode == "backfill" and not backfill_done


def _persist_articles_batched(
    articles: list[RawNewsArticle],
    *,
    cfg: NewsParserConfig,
    mode: CollectMode,
    source_key: str,
    street_index: MoscowStreetIndex | None,
) -> tuple[int, int, datetime | None, datetime | None]:
    batch_size = max(1, cfg.insert_batch_size)
    created = 0
    skipped = 0
    oldest_at: datetime | None = None
    newest_at: datetime | None = None
    known_streak = 0

    article_ids = [a.source_msg_id for a in articles]
    with session_scope() as session:
        existing = list_existing_source_msg_ids(
            session,
            source=EventSource.NEWS.value,
            source_msg_ids=article_ids,
        )

    pending: list[RawNewsArticle] = []
    for article in articles:
        published_at = article.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        if oldest_at is None or published_at < oldest_at:
            oldest_at = published_at
        if newest_at is None or published_at > newest_at:
            newest_at = published_at

        if article.source_msg_id in existing:
            skipped += 1
            if mode == "incremental":
                known_streak += 1
                if known_streak >= cfg.early_stop_known_streak:
                    logger.info(
                        "Ранний стоп incremental %s: серия %d известных id",
                        source_key,
                        known_streak,
                    )
                    break
            continue

        known_streak = 0
        pending.append(article)
        if len(pending) >= batch_size:
            c, s = _flush_batch(pending, existing=existing, street_index=street_index)
            created += c
            skipped += s
            logger.info("Источник %s: батч записан +%d (всего создано=%d)", source_key, c, created)
            pending = []

    if pending:
        c, s = _flush_batch(pending, existing=existing, street_index=street_index)
        created += c
        skipped += s
        logger.info("Источник %s: батч записан +%d (всего создано=%d)", source_key, c, created)

    return created, skipped, oldest_at, newest_at


def _flush_batch(
    batch: list[RawNewsArticle],
    *,
    existing: set[str],
    street_index: MoscowStreetIndex | None,
) -> tuple[int, int]:
    created = 0
    skipped = 0
    with session_scope() as session:
        for article in batch:
            if article.source_msg_id in existing:
                skipped += 1
                continue
            address_id = resolve_article_address(
                session,
                article,
                street_index=street_index,
            )
            event = persist_article(session, article, address_id=address_id)
            if event is None:
                skipped += 1
                existing.add(article.source_msg_id)
                continue
            created += 1
            existing.add(article.source_msg_id)
    return created, skipped


async def run_news_parser() -> None:
    settings = get_settings()
    cfg = settings.news_parser

    if not settings.runtime.enable_news_parser:
        logger.info("Парсер новостей отключён (runtime.enable_news_parser=false)")
        return

    sources = get_sources(cfg)
    logger.info(
        "Старт парсера новостей: источников=%d max_per_source_per_run=%d "
        "batch=%d poll=%ds lookback=%d",
        len(sources),
        cfg.max_articles_per_source_per_run,
        cfg.insert_batch_size,
        cfg.poll_interval_seconds,
        cfg.lookback_days,
    )

    street_index: MoscowStreetIndex | None = None
    try:
        with session_scope() as session:
            street_index = MoscowStreetIndex.load(session)
    except Exception:
        logger.exception("Не удалось загрузить индекс улиц — geo только по индексу")

    async with make_client(settings) as client:
        while True:
            any_backfill_pending = False
            for source in sources:
                try:
                    pending = await _process_source(
                        client,
                        source,
                        cfg,
                        street_index=street_index,
                    )
                    any_backfill_pending = any_backfill_pending or pending
                except Exception as exc:
                    logger.exception("Необработанная ошибка источника %s: %s", source.key, exc)
                    try:
                        with session_scope() as session:
                            cursor = get_or_create_cursor(session, source.key)
                            update_cursor(
                                session,
                                cursor,
                                last_run_at=datetime.now(UTC),
                                last_error=str(exc),
                            )
                    except Exception:
                        logger.exception("Не удалось записать last_error для %s", source.key)

            if any_backfill_pending:
                # Не ждать час между пачками backfill — иначе кажется, что «остановились на 500».
                logger.info("Backfill не завершён — следующий круг без длинной паузы")
                await asyncio.sleep(1)
            else:
                logger.info(
                    "Все источники в incremental — сон %d сек",
                    cfg.poll_interval_seconds,
                )
                await asyncio.sleep(cfg.poll_interval_seconds)
