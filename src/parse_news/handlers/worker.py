"""Оркестратор парсера новостей (бесконечный poll-цикл)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from address.street_catalog import StreetCatalog
from events.handlers.crud import list_existing_source_msg_ids
from events.models.event import EventSource
from parse_news.handlers.geo import resolve_article_geo
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


def _need_backfill(
    *,
    backfill_complete: bool,
    outlet_event_count: int,
    parser_mode: str,
) -> bool:
    # bootstrap: только быстрый RSS/incremental, без HTML-архивов.
    if parser_mode == "bootstrap":
        return False
    return (not backfill_complete) or outlet_event_count == 0


def _backfill_done_after_collect(
    *,
    previous_complete: bool,
    mode: CollectMode,
    result: CollectResult,
    max_articles: int,
    parser_mode: str,
    outlet_event_count: int,
    bootstrap_target: int,
) -> bool:
    """
    backfill_complete:

    - bootstrap: после одной пачки (или когда уже >= N событий) — хватит для демо;
    - production: только когда реально дошли до lookback (reached_since / архив исчерпан).
    """
    if previous_complete and mode != "backfill":
        return True
    if mode != "backfill":
        return previous_complete

    if parser_mode == "bootstrap":
        if outlet_event_count >= bootstrap_target:
            return True
        # Одна успешная пачка backfill → дальше incremental (realtime).
        return bool(result.articles) or result.reached_since or result.next_cursor is None

    if result.reached_since:
        return True
    if len(result.articles) >= max_articles:
        return False
    return result.next_cursor is None


async def _process_source(
    client: httpx.AsyncClient,
    source: NewsSource,
    cfg: NewsParserConfig,
    *,
    street_index: StreetCatalog | None,
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
            parser_mode=cfg.mode,
        )
        mode: CollectMode = "backfill" if need_backfill else "incremental"
        listing_cursor = cursor.listing_cursor
        previous_complete = cursor.backfill_complete

    since = datetime.now(UTC) - timedelta(days=cfg.lookback_days)
    max_per_run = cfg.max_articles_per_source_per_run
    if cfg.mode == "bootstrap":
        max_per_run = min(max_per_run, cfg.bootstrap_articles_per_source)

    logger.info(
        "Источник %s: mode=%s parser=%s since=%s cursor=%s max_per_run=%d pages=%d",
        source_key,
        mode,
        cfg.mode,
        since.date().isoformat(),
        listing_cursor,
        max_per_run,
        cfg.max_pages_per_run,
    )

    try:
        result = await asyncio.wait_for(
            source.collect(
                client,
                since=since,
                mode=mode,
                listing_cursor=listing_cursor,
                max_articles=max_per_run,
                max_pages=cfg.max_pages_per_run,
            ),
            timeout=float(cfg.collect_timeout_seconds),
        )
    except TimeoutError:
        msg = f"collect timeout after {cfg.collect_timeout_seconds}s"
        logger.error("Таймаут collect для %s: %s", source_key, msg)
        with session_scope() as session:
            cursor = get_or_create_cursor(session, source_key)
            update_cursor(
                session,
                cursor,
                last_run_at=datetime.now(UTC),
                last_error=msg,
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
        max_articles=max_per_run,
        parser_mode=cfg.mode,
        outlet_event_count=outlet_count + created,
        bootstrap_target=cfg.bootstrap_articles_per_source,
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
    street_index: StreetCatalog | None,
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
    street_index: StreetCatalog | None,
) -> tuple[int, int]:
    created = 0
    skipped = 0
    with session_scope() as session:
        for article in batch:
            if article.source_msg_id in existing:
                skipped += 1
                continue
            geo = resolve_article_geo(
                session,
                article,
                street_index=street_index,
            )
            event = persist_article(session, article, geo=geo)
            if event is None:
                skipped += 1
                existing.add(article.source_msg_id)
                continue
            created += 1
            existing.add(article.source_msg_id)
    return created, skipped


async def run_news_parser() -> None:
    from pathlib import Path

    from parse_news.seed import DEFAULT_SNAPSHOT, dump_events_snapshot, ensure_events_seeded

    settings = get_settings()
    cfg = settings.news_parser

    if not settings.runtime.enable_news_parser:
        logger.info("Парсер новостей отключён (runtime.enable_news_parser=false)")
        return

    snap_path = Path(cfg.bootstrap_snapshot_path)
    if not snap_path.is_absolute():
        snap_path = Path(__file__).resolve().parents[3] / snap_path
    if not snap_path.is_file():
        snap_path = DEFAULT_SNAPSHOT

    try:
        if ensure_events_seeded(snap_path):
            logger.info("События загружены из snapshot %s", snap_path)
    except Exception:
        logger.exception("Не удалось загрузить snapshot событий — продолжаем парсинг")

    sources = get_sources(cfg)
    logger.info(
        "Старт парсера новостей: mode=%s источников=%d max_per_run=%d poll=%ds",
        cfg.mode,
        len(sources),
        cfg.max_articles_per_source_per_run,
        cfg.poll_interval_seconds,
    )

    street_index: StreetCatalog | None = None
    try:
        with session_scope() as session:
            street_index = StreetCatalog.load(session)
    except Exception:
        logger.exception("Не удалось загрузить индекс улиц — geo только по индексу")

    snapshot_dumped = snap_path.is_file()
    while True:
        try:
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
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            logger.exception(
                                "Необработанная ошибка источника %s: %s",
                                source.key,
                                exc,
                            )
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
                                logger.exception(
                                    "Не удалось записать last_error для %s", source.key
                                )

                    if not snapshot_dumped and not any_backfill_pending and cfg.mode == "bootstrap":
                        try:
                            with session_scope() as session:
                                n = dump_events_snapshot(
                                    session,
                                    snap_path,
                                    limit=max(100, cfg.bootstrap_articles_per_source * 6),
                                )
                            snapshot_dumped = n > 0
                            logger.info(
                                "Bootstrap snapshot сохранён: %d событий → %s",
                                n,
                                snap_path,
                            )
                        except Exception:
                            logger.exception("Не удалось сохранить bootstrap snapshot")

                    if any_backfill_pending:
                        logger.info("Backfill не завершён — следующий круг без длинной паузы")
                        await asyncio.sleep(1)
                    else:
                        logger.info(
                            "Все источники в incremental — сон %d сек",
                            cfg.poll_interval_seconds,
                        )
                        await asyncio.sleep(cfg.poll_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Сбой HTTP-клиента парсера — пересоздаём через 5с")
            await asyncio.sleep(5)
