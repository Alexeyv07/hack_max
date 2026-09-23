"""Фоновый worker уведомлений: личные priority-пуши и суммаризация домовых чатов."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from notify.chat_source import ChatMessage, ChatMessageLoader, load_chat_messages
from notify.db import NotifyChatMessageRow
from notify.digest import (
    DigestTarget,
    build_template_digest,
    decorate_digest,
    digest_cursor,
    digest_message_id,
    digest_scheduled_at,
    list_due_digest_targets,
    mark_digest_done,
    normalize_messages,
)
from notify.priority import (
    PriorityDelivery,
    ack_payload,
    build_priority_text,
    delivery_is_due,
    enqueue_new_priority_deliveries,
    list_due_priority_deliveries,
    mark_delivery_sent,
)
from notify.summarizer import summarize_digest
from project.config import NotifyConfig, get_settings
from project.database import get_session_factory
from project.logging_setup import get_logger
from project.max_runtime import get_max_bot

logger = get_logger(__name__)

PriorityKeyboardFactory = Callable[[PriorityDelivery], Any]
DigestSummarizer = Callable[[Sequence[ChatMessage], NotifyConfig], Awaitable[str | None]]


async def _summarize_digest(messages: Sequence[ChatMessage], config: NotifyConfig) -> str | None:
    return await summarize_digest(messages, config=config)


def _build_priority_keyboard(delivery: PriorityDelivery) -> Any:
    # Локальный импорт: unit-тесты priority не требуют установленного maxapi.
    from maxapi.types import CallbackButton
    from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="Увидел", payload=ack_payload(delivery.delivery_id)))
    return builder.as_markup()


def _target_is_still_due(
    session: Session,
    *,
    target: DigestTarget,
    now: datetime,
    config: NotifyConfig,
) -> bool:
    from notify.db import NotifyDigestRow

    local_now = now.astimezone(ZoneInfo(config.timezone))
    state = session.get(NotifyDigestRow, target.chat_id)
    if state is not None and state.last_digest_date == local_now.date():
        return False
    return local_now >= digest_scheduled_at(target.chat_id, local_now.date(), config)


def _bot_join_link(bot: Any) -> str | None:
    username = getattr(getattr(bot, "me", None), "username", None)
    if not username:
        return None
    return f"https://max.ru/{username}"


async def run_priority_cycle(
    bot: Any,
    *,
    now: datetime | None = None,
    config: NotifyConfig | None = None,
    session_factory: sessionmaker[Session] | None = None,
    keyboard_factory: PriorityKeyboardFactory = _build_priority_keyboard,
) -> int:
    """Создать новые personal deliveries и отправить все due/retry."""
    cfg = config or get_settings().notify
    current = now or datetime.now(UTC)
    factory = session_factory or get_session_factory()

    with factory() as session:
        enqueue_new_priority_deliveries(session)
        session.commit()

    with factory() as session:
        due = list_due_priority_deliveries(
            session,
            now=current,
            retry_interval_seconds=cfg.retry_interval_seconds,
        )

    sent = 0
    for delivery in due:
        with factory() as session:
            if not delivery_is_due(
                session,
                delivery_id=delivery.delivery_id,
                now=current,
                retry_interval_seconds=cfg.retry_interval_seconds,
            ):
                continue

        try:
            await bot.send_message(
                chat_id=delivery.chat_id,
                text=build_priority_text(delivery),
                attachments=[keyboard_factory(delivery)],
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Не удалось отправить личное priority-уведомление",
                extra={
                    "delivery_id": delivery.delivery_id,
                    "event_id": delivery.event_id,
                    "user_id": delivery.user_id,
                },
            )
            continue

        with factory() as session:
            if mark_delivery_sent(
                session,
                delivery_id=delivery.delivery_id,
                sent_at=current,
            ):
                session.commit()
                sent += 1

    return sent


async def run_digest_cycle(
    bot: Any,
    *,
    now: datetime | None = None,
    config: NotifyConfig | None = None,
    session_factory: sessionmaker[Session] | None = None,
    message_loader: ChatMessageLoader = load_chat_messages,
    summarizer: DigestSummarizer = _summarize_digest,
) -> int:
    """Раз в день проверить новые сообщения и суммаризировать только если их > threshold."""
    cfg = config or get_settings().notify
    current = now or datetime.now(UTC)
    factory = session_factory or get_session_factory()

    with factory() as session:
        due_targets = list_due_digest_targets(session, now=current, config=cfg)

    sent = 0
    for target in due_targets:
        with factory() as session:
            if not _target_is_still_due(session, target=target, now=current, config=cfg):
                continue
            after = digest_cursor(session, target.chat_id)
            after_id = digest_message_id(session, target.chat_id)

        if message_loader is load_chat_messages:
            loaded = await message_loader(target.chat_id, after, after_id=after_id)
        else:
            # Старый интерфейс остаётся доступным для тестов/других адаптеров.
            loaded = await message_loader(target.chat_id, after)
        messages = normalize_messages(list(loaded))
        local_day = current.astimezone(ZoneInfo(cfg.timezone)).date()

        # По договорённости: 30 недостаточно, суммаризация начинается только с 31-го нового сообщения.
        if len(messages) <= max(0, cfg.digest_min_new_messages):
            with factory() as session:
                mark_digest_done(
                    session,
                    chat_id=target.chat_id,
                    day=local_day,
                    sent_at=None,
                )
                session.commit()
            continue

        text = await summarizer(messages, cfg)
        if text is None:
            text = build_template_digest(messages)
        if text is None:
            continue

        text = decorate_digest(text, bot_link=_bot_join_link(bot))
        try:
            await bot.send_message(chat_id=target.chat_id, text=text, format="markdown")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Не удалось отправить суммаризацию чата",
                extra={"chat_id": target.chat_id},
            )
            continue

        last_message_at = max(message.created_at for message in messages)
        last_message_id = max(
            (message.row_id for message in messages if message.row_id is not None),
            default=None,
        )
        with factory() as session:
            mark_digest_done(
                session,
                chat_id=target.chat_id,
                day=local_day,
                sent_at=current,
                last_message_at=last_message_at,
                last_message_id=last_message_id,
            )
            if last_message_id is not None:
                # После успешной отправки больше не держим обработанные тексты.
                session.execute(
                    delete(NotifyChatMessageRow).where(
                        NotifyChatMessageRow.chat_id == target.chat_id,
                        NotifyChatMessageRow.id <= last_message_id,
                    )
                )
            session.commit()
        sent += 1

    return sent


async def run_notify_worker() -> None:
    """Периодически запускает notify-задачи; включается только NOTIFY_ENABLED=true."""
    cfg = get_settings().notify
    if not cfg.enabled:
        logger.info("Notify worker выключен (NOTIFY_ENABLED=false)")
        return

    logger.info(
        "Notify worker запущен: digest_hour=%s jitter=±%smin min_messages=>%s retry=%ss poll=%ss",
        cfg.digest_hour,
        cfg.digest_jitter_minutes,
        cfg.digest_min_new_messages,
        cfg.retry_interval_seconds,
        cfg.poll_interval_seconds,
    )
    while True:
        bot = get_max_bot()
        if bot is None:
            logger.debug("Notify worker ждёт запуска MAX bot")
        else:
            await run_priority_cycle(bot, config=cfg)
            await run_digest_cycle(bot, config=cfg)
        await asyncio.sleep(max(1, cfg.poll_interval_seconds))
