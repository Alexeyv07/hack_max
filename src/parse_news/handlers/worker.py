"""Оркестратор парсера новостей (бесконечный poll-цикл)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from address.street_catalog import StreetCatalog
from events.handlers.crud import list_existing_source_msg_ids
from events.models.event import EventSource
from parse_news.handlers.geo import resolve_article_geo, should_skip_foreign_article
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


async def _in_thread[**P, T](fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Синхронный CPU/DB/ONNX — вне event loop, чтобы API и бот не голодали."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _need_backfill(
    *,
    backfill_complete: bool,
    outlet_event_count: int,
    oldest_seen_at: datetime | None = None,
    lookback_since: datetime | None = None,
) -> bool:
    """Нужен HTML/archive backfill до lookback_since (и bootstrap, и production)."""
    if outlet_event_count == 0:
        return True
    if not backfill_complete:
        return True
    # Курсор помечен complete слишком рано (старый bootstrap) — ещё не дотянули lookback.
    oldest = _aware(oldest_seen_at)
    since = _aware(lookback_since)
    return oldest is not None and since is not None and oldest > since


def _backfill_done_after_collect(
    *,
    previous_complete: bool,
    mode: CollectMode,
    result: CollectResult,
    max_articles: int,
    outlet_event_count: int,
    soft_cap: int,
) -> bool:
    """
    backfill_complete, когда реально дошли до lookback (reached_since / архив исчерпан).

    soft_cap > 0 (bootstrap_articles_per_source) — опциональный потолок на outlet для демо;
    0 = без потолка, тянем весь lookback_days.
    """
    if previous_complete and mode != "backfill":
        return True
    if mode != "backfill":
        return previous_complete

    if soft_cap > 0 and outlet_event_count >= soft_cap:
        return True
    if result.reached_since:
        return True
    if len(result.articles) >= max_articles:
        return False
    return result.next_cursor is None


def _load_source_plan(
    source_key: str,
    *,
    lookback_days: int,
) -> tuple[CollectMode, str | None, bool, int, datetime]:
    """Курсор + режим collect (синхронно, для to_thread)."""
    since = datetime.now(UTC) - timedelta(days=max(1, lookback_days))
    with session_scope() as session:
        cursor = get_or_create_cursor(session, source_key)
        outlet_count = count_events_for_outlet(session, source_key)
        need_backfill = _need_backfill(
            backfill_complete=cursor.backfill_complete,
            outlet_event_count=outlet_count,
            oldest_seen_at=cursor.oldest_seen_at,
            lookback_since=since,
        )
        mode: CollectMode = "backfill" if need_backfill else "incremental"
        listing_cursor = cursor.listing_cursor
        previous_complete = cursor.backfill_complete
        if need_backfill and previous_complete:
            listing_cursor = None
            previous_complete = False
        return mode, listing_cursor, previous_complete, outlet_count, since


def _mark_backfill_complete(source_key: str) -> None:
    with session_scope() as session:
        cursor = get_or_create_cursor(session, source_key)
        update_cursor(
            session,
            cursor,
            backfill_complete=True,
            last_run_at=datetime.now(UTC),
            clear_error=True,
        )


def _record_source_error(source_key: str, message: str) -> None:
    with session_scope() as session:
        cursor = get_or_create_cursor(session, source_key)
        update_cursor(
            session,
            cursor,
            last_run_at=datetime.now(UTC),
            last_error=message,
        )


def _commit_source_progress(
    source_key: str,
    *,
    listing_cursor: str | None,
    backfill_complete: bool,
    oldest_seen_at: datetime | None,
    newest_seen_at: datetime | None,
) -> None:
    with session_scope() as session:
        cursor = get_or_create_cursor(session, source_key)
        cursor.listing_cursor = listing_cursor
        update_cursor(
            session,
            cursor,
            backfill_complete=backfill_complete,
            oldest_seen_at=oldest_seen_at,
            newest_seen_at=newest_seen_at,
            last_run_at=datetime.now(UTC),
            clear_error=True,
        )


def _load_street_index() -> StreetCatalog | None:
    with session_scope() as session:
        return StreetCatalog.load(session)


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

    mode, listing_cursor, previous_complete, outlet_count, since = await _in_thread(
        _load_source_plan,
        source_key,
        lookback_days=cfg.lookback_days,
    )

    max_per_run = max(1, cfg.max_articles_per_source_per_run)
    soft_cap = max(0, cfg.bootstrap_articles_per_source)
    # В bootstrap soft_cap ограничивает объём на outlet; за прогон не берём больше остатка.
    if cfg.mode == "bootstrap" and soft_cap > 0:
        remaining = max(0, soft_cap - outlet_count)
        max_per_run = 0 if remaining == 0 else min(max_per_run, remaining)

    logger.info(
        "Источник %s: mode=%s parser=%s since=%s cursor=%s max_per_run=%d pages=%d soft_cap=%d",
        source_key,
        mode,
        cfg.mode,
        since.date().isoformat(),
        listing_cursor,
        max_per_run,
        cfg.max_pages_per_run,
        soft_cap,
    )

    if max_per_run == 0:
        await _in_thread(_mark_backfill_complete, source_key)
        return False

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
        await _in_thread(_record_source_error, source_key, msg)
        return False
    except Exception as exc:
        logger.exception("Ошибка collect для %s: %s", source_key, exc)
        await _in_thread(_record_source_error, source_key, str(exc))
        return False

    # ONNX classify + geo + INSERT — главная причина «заморозки» HTTP.
    created, skipped, oldest_at, newest_at = await _in_thread(
        _persist_articles_batched,
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
        outlet_event_count=outlet_count + created,
        soft_cap=soft_cap if cfg.mode == "bootstrap" else 0,
    )
    # Если упёрлись в лимит, а курсора нет — сохраняем listing_cursor как был,
    # чтобы не потерять прогресс; иначе пишем next_cursor.
    if mode == "backfill" and not backfill_done:
        new_cursor = result.next_cursor if result.next_cursor is not None else listing_cursor
    else:
        new_cursor = None if backfill_done else result.next_cursor

    await _in_thread(
        _commit_source_progress,
        source_key,
        listing_cursor=new_cursor,
        backfill_complete=backfill_done,
        oldest_seen_at=oldest_at,
        newest_seen_at=newest_at,
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
            if should_skip_foreign_article(article):
                logger.info(
                    "Пропуск иностранной географии %s: %s",
                    article.source_msg_id,
                    (article.title or "")[:80],
                )
                skipped += 1
                existing.add(article.source_msg_id)
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

    from parser_common.seed import DEFAULT_SNAPSHOT, dump_events_snapshot, ensure_events_seeded

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
        if await _in_thread(ensure_events_seeded, snap_path):
            logger.info("События загружены из snapshot %s", snap_path)
    except Exception:
        logger.exception("Не удалось загрузить snapshot событий — продолжаем парсинг")

    sources = get_sources(cfg)
    logger.info(
        "Старт парсера новостей: mode=%s источников=%d max_per_run=%d poll=%ds "
        "source_pause=%.2fs backfill_pause=%.2fs",
        cfg.mode,
        len(sources),
        cfg.max_articles_per_source_per_run,
        cfg.poll_interval_seconds,
        cfg.source_pause_seconds,
        cfg.backfill_pause_seconds,
    )

    street_index: StreetCatalog | None = None
    try:
        street_index = await _in_thread(_load_street_index)
    except Exception:
        logger.exception("Не удалось загрузить индекс улиц — geo только по индексу")

    snapshot_dumped = snap_path.is_file()
    source_pause = max(0.0, float(cfg.source_pause_seconds))
    backfill_pause = max(0.0, float(cfg.backfill_pause_seconds))

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
                                await _in_thread(_record_source_error, source.key, str(exc))
                            except Exception:
                                logger.exception(
                                    "Не удалось записать last_error для %s", source.key
                                )
                        if source_pause > 0:
                            await asyncio.sleep(source_pause)

                    if not snapshot_dumped and not any_backfill_pending and cfg.mode == "bootstrap":
                        try:

                            def _dump() -> int:
                                with session_scope() as session:
                                    return dump_events_snapshot(
                                        session,
                                        snap_path,
                                        limit=max(
                                            2000,
                                            cfg.bootstrap_articles_per_source * 6
                                            if cfg.bootstrap_articles_per_source > 0
                                            else cfg.lookback_days * 400,
                                        ),
                                    )

                            n = await _in_thread(_dump)
                            snapshot_dumped = n > 0
                            logger.info(
                                "Bootstrap snapshot сохранён: %d событий → %s",
                                n,
                                snap_path,
                            )
                        except Exception:
                            logger.exception("Не удалось сохранить bootstrap snapshot")

                    if any_backfill_pending:
                        logger.info(
                            "Backfill не завершён — пауза %.1fs (API/бот приоритетнее)",
                            backfill_pause,
                        )
                        if backfill_pause > 0:
                            await asyncio.sleep(backfill_pause)
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
