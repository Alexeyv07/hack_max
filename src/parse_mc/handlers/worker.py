"""Оркестратор парсера УК/ЖЭК (бесконечный poll-цикл)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from address.street_catalog import StreetCatalog
from events.handlers.crud import list_existing_source_msg_ids
from events.models.event import EventSource
from parse_mc.handlers.geo import resolve_notice_geos, should_skip_foreign_notice
from parse_mc.handlers.ingest import persist_notice
from parse_mc.handlers.state import (
    count_events_for_outlet,
    get_or_create_cursor,
    update_cursor,
)
from parse_mc.http import make_client
from parse_mc.models.notice import RawMcNotice
from parse_mc.registry import get_sources
from parse_mc.sources.base import CollectMode, CollectResult, McSource
from project.config import McParserConfig, get_settings
from project.database import session_scope
from project.logging_setup import get_logger

logger = get_logger(__name__)


async def _in_thread[**P, T](fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
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
    if outlet_event_count == 0:
        return True
    if not backfill_complete:
        return True
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
    if previous_complete and mode != "backfill":
        return True
    if mode != "backfill":
        return previous_complete
    if soft_cap > 0 and outlet_event_count >= soft_cap:
        return True
    if result.reached_since:
        return True
    if len(result.notices) >= max_articles:
        return False
    return result.next_cursor is None


def _load_source_plan(
    source_key: str,
    *,
    lookback_days: int,
) -> tuple[CollectMode, str | None, bool, int, datetime]:
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
    source: McSource,
    cfg: McParserConfig,
    *,
    street_index: StreetCatalog | None,
) -> bool:
    source_key = source.key
    logger.info("Запуск УК-источника %s", source_key)

    mode, listing_cursor, previous_complete, outlet_count, since = await _in_thread(
        _load_source_plan,
        source_key,
        lookback_days=cfg.lookback_days,
    )

    max_per_run = max(1, cfg.max_articles_per_source_per_run)
    soft_cap = max(0, cfg.bootstrap_articles_per_source)
    if cfg.mode == "bootstrap" and soft_cap > 0:
        remaining = max(0, soft_cap - outlet_count)
        max_per_run = 0 if remaining == 0 else min(max_per_run, remaining)

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

    created, skipped, oldest_at, newest_at = await _in_thread(
        _persist_notices_batched,
        result.notices,
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
        "УК-источник %s: создано=%d пропущено=%d fetched=%d backfill_complete=%s",
        source_key,
        created,
        skipped,
        len(result.notices),
        backfill_done,
    )
    return mode == "backfill" and not backfill_done


def _persist_notices_batched(
    notices: list[RawMcNotice],
    *,
    cfg: McParserConfig,
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

    base_ids = [n.source_msg_id for n in notices]
    with session_scope() as session:
        existing = list_existing_source_msg_ids(
            session,
            source=EventSource.MC.value,
            source_msg_ids=base_ids,
        )

    pending: list[RawMcNotice] = []
    for notice in notices:
        published_at = notice.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        if oldest_at is None or published_at < oldest_at:
            oldest_at = published_at
        if newest_at is None or published_at > newest_at:
            newest_at = published_at

        # Базовый id известен → возможно уже писали (в т.ч. fan-out); early-stop.
        if notice.source_msg_id in existing or any(
            eid.startswith(f"{notice.source_msg_id}:addr:") for eid in existing
        ):
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
        pending.append(notice)
        if len(pending) >= batch_size:
            c, s = _flush_batch(pending, existing=existing, street_index=street_index)
            created += c
            skipped += s
            pending = []

    if pending:
        c, s = _flush_batch(pending, existing=existing, street_index=street_index)
        created += c
        skipped += s

    return created, skipped, oldest_at, newest_at


def _flush_batch(
    batch: list[RawMcNotice],
    *,
    existing: set[str],
    street_index: StreetCatalog | None,
) -> tuple[int, int]:
    created = 0
    skipped = 0
    with session_scope() as session:
        for notice in batch:
            if should_skip_foreign_notice(notice):
                skipped += 1
                existing.add(notice.source_msg_id)
                continue
            geos = resolve_notice_geos(session, notice, street_index=street_index)
            events = persist_notice(session, notice, geos=geos)
            if not events:
                skipped += 1
                existing.add(notice.source_msg_id)
                continue
            created += len(events)
            for event in events:
                if event.source_msg_id:
                    existing.add(event.source_msg_id)
            existing.add(notice.source_msg_id)
    return created, skipped


async def run_mc_parser() -> None:
    settings = get_settings()
    cfg = settings.mc_parser

    if not settings.runtime.enable_mc_parser:
        logger.info("Парсер УК отключён (runtime.enable_mc_parser=false)")
        return

    sources = get_sources(cfg)
    logger.info(
        "Старт парсера УК/ЖЭК: mode=%s источников=%d max_per_run=%d poll=%ds",
        cfg.mode,
        len(sources),
        cfg.max_articles_per_source_per_run,
        cfg.poll_interval_seconds,
    )

    street_index: StreetCatalog | None = None
    try:
        street_index = await _in_thread(_load_street_index)
    except Exception:
        logger.exception("Не удалось загрузить индекс улиц — geo только city/fallback")

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
                                "Необработанная ошибка УК-источника %s: %s",
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

                    if any_backfill_pending:
                        if backfill_pause > 0:
                            await asyncio.sleep(backfill_pause)
                    else:
                        await asyncio.sleep(cfg.poll_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Сбой HTTP-клиента парсера УК — пересоздаём через 5с")
            await asyncio.sleep(5)
