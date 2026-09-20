"""Решение NEW | DUPLICATE | UPDATE + применение к БД."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from re import IGNORECASE, search

from sqlalchemy import select
from sqlalchemy.orm import Session

from events.db.event import EventRow
from events.handlers.crud import create_event, get_event, list_existing_source_msg_ids, update_event
from events.models.event import Event, EventUpdate
from ml_dedup.active import list_active_events
from ml_dedup.embed import cosine, embed_text, haversine_m
from ml_dedup.models import ActiveEventView
from parser_common.models.draft import EventDraft
from parser_common.normalize import to_event_create
from project.logging_setup import get_logger

logger = get_logger(__name__)

_UPDATE_HINTS = (
    r"устран",
    r"восстанов",
    r"завершен",
    r"завершён",
    r"подали\s+воду",
    r"включили",
    r"локализован",
    r"продлен",
    r"продлён",
    r"перенес",
    r"обновлен",
    r"обновлён",
    r"актуализац",
    r"ликвидир",
)


class DedupAction(StrEnum):
    NEW = "new"
    DUPLICATE = "duplicate"
    UPDATE = "update"


@dataclass(frozen=True, slots=True)
class DedupDecision:
    action: DedupAction
    match: ActiveEventView | None = None
    score: float = 0.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class DedupConfig:
    enabled: bool = True
    active_days: int = 21
    duplicate_threshold: float = 0.88
    update_threshold: float = 0.72
    radius_m: float = 3000.0
    allow_hash_fallback: bool = True
    require_geo_match: bool = False


def _load_dedup_config() -> DedupConfig:
    try:
        from project.config import get_settings

        cfg = get_settings().ml_dedup
        return DedupConfig(
            enabled=cfg.enabled,
            active_days=cfg.active_days,
            duplicate_threshold=cfg.duplicate_threshold,
            update_threshold=cfg.update_threshold,
            radius_m=cfg.radius_m,
            allow_hash_fallback=cfg.allow_hash_fallback,
            require_geo_match=cfg.require_geo_match,
        )
    except Exception:
        return DedupConfig()


def _text_blob(title: str, body: str) -> str:
    return f"{title}\n{body}".strip()


def _has_update_hint(text: str) -> bool:
    return any(search(pat, text, IGNORECASE) for pat in _UPDATE_HINTS)


def _geo_nearby(
    draft: EventDraft,
    event: ActiveEventView,
    *,
    radius_m: float,
    draft_lat: float | None = None,
    draft_lon: float | None = None,
) -> bool:
    """Совместимы ли локации для DUP/UPDATE (без «склейки» чужих адресов)."""
    # Разные address_id — всегда конфликт, даже если точки в радиусе 3 км.
    if draft.address_id is not None and event.address_id is not None:
        return draft.address_id == event.address_id

    if (
        draft_lat is not None
        and draft_lon is not None
        and event.lat is not None
        and event.lon is not None
    ):
        return haversine_m(draft_lat, draft_lon, event.lat, event.lon) <= radius_m

    # Один с адресом, другой без — не считаем «рядом».
    return draft.address_id is None and event.address_id is None


def _address_ids_conflict(draft: EventDraft, event: ActiveEventView) -> bool:
    """Оба адреса заданы и различаются → нельзя DUPLICATE/UPDATE."""
    return (
        draft.address_id is not None
        and event.address_id is not None
        and draft.address_id != event.address_id
    )


def decide_relation(
    draft: EventDraft,
    candidates: list[ActiveEventView],
    *,
    config: DedupConfig | None = None,
    draft_lat: float | None = None,
    draft_lon: float | None = None,
) -> DedupDecision:
    cfg = config or _load_dedup_config()
    if not candidates:
        return DedupDecision(DedupAction.NEW, reason="no_candidates")

    incoming = _text_blob(draft.title, draft.body)
    incoming_vec = embed_text(incoming, allow_hash_fallback=cfg.allow_hash_fallback)
    update_hint = _has_update_hint(incoming)

    best: tuple[float, ActiveEventView] | None = None
    for event in candidates:
        # Жёсткое правило: разные адреса/регионы не склеиваем (даже при score 0.85+).
        if _address_ids_conflict(draft, event):
            continue
        if cfg.require_geo_match and not _geo_nearby(
            draft, event, radius_m=cfg.radius_m, draft_lat=draft_lat, draft_lon=draft_lon
        ):
            continue

        other = _text_blob(event.title, event.body)
        score = cosine(incoming_vec, embed_text(other, allow_hash_fallback=cfg.allow_hash_fallback))
        if best is None or score > best[0]:
            best = (score, event)

    if best is None:
        return DedupDecision(DedupAction.NEW, reason="geo_filtered")

    score, match = best
    # Safety: после выбора best ещё раз не пропускаем конфликт адресов в DUPLICATE.
    if score >= cfg.duplicate_threshold:
        if _address_ids_conflict(draft, match):
            return DedupDecision(
                DedupAction.NEW,
                match=match,
                score=score,
                reason="geo_address_mismatch",
            )
        if update_hint and score < 0.97:
            return DedupDecision(
                DedupAction.UPDATE,
                match=match,
                score=score,
                reason="near_dup_with_update_hint",
            )
        return DedupDecision(
            DedupAction.DUPLICATE,
            match=match,
            score=score,
            reason="cosine_duplicate",
        )

    mid = (cfg.update_threshold + cfg.duplicate_threshold) / 2
    if score >= cfg.update_threshold and (update_hint or score >= mid):
        if _address_ids_conflict(draft, match):
            return DedupDecision(
                DedupAction.NEW,
                match=match,
                score=score,
                reason="geo_address_mismatch",
            )
        return DedupDecision(
            DedupAction.UPDATE,
            match=match,
            score=score,
            reason="cosine_update" + ("_hint" if update_hint else ""),
        )

    return DedupDecision(DedupAction.NEW, match=match, score=score, reason="below_threshold")


def build_update_payload(existing: ActiveEventView, draft: EventDraft) -> EventUpdate:
    """Смержить поля: свежий текст, max importance, OR disaster, окна дат."""
    new_title = draft.title.strip()
    new_body = draft.body.strip()
    if new_body and new_body not in (existing.body or ""):
        body = new_body
        title = new_title or existing.title
    else:
        body = existing.body
        title = existing.title

    return EventUpdate(
        title=title,
        body=body,
        importance=max(existing.importance, draft.importance),
        disaster_flag=existing.disaster_flag or draft.disaster_flag,
        address_id=draft.address_id if draft.address_id is not None else None,
        geo_by=draft.geo_by if draft.geo_by is not None else None,
        source_url=draft.source_url or existing.source_url,
        image_url=draft.image_url if draft.image_url is not None else None,
        published_at=draft.published_at,
        active_from=draft.active_from,
        active_to=draft.active_to,
    )


def resolve_draft(
    session: Session,
    draft: EventDraft,
    *,
    config: DedupConfig | None = None,
    now: datetime | None = None,
) -> tuple[DedupDecision, Event | None]:
    """
    Применить dedup к EventDraft.

    Returns:
      (decision, event|None) — DUPLICATE=существующий; UPDATE=обновлённый; NEW=созданный.
    """
    cfg = config or _load_dedup_config()
    if not cfg.enabled:
        event = create_event(session, to_event_create(draft))
        return DedupDecision(DedupAction.NEW, reason="disabled"), event

    if draft.source_msg_id:
        existing_ids = list_existing_source_msg_ids(
            session,
            source=draft.source,
            source_msg_ids=[draft.source_msg_id],
        )
        if draft.source_msg_id in existing_ids:
            row = session.scalar(
                select(EventRow).where(
                    EventRow.source == draft.source,
                    EventRow.source_msg_id == draft.source_msg_id,
                )
            )
            if row is not None:
                return (
                    DedupDecision(DedupAction.DUPLICATE, reason="source_msg_id"),
                    get_event(session, row.id),
                )

    candidates = list_active_events(
        session,
        active_days=cfg.active_days,
        now=now or datetime.now(UTC),
    )
    decision = decide_relation(draft, candidates, config=cfg)

    if decision.action == DedupAction.DUPLICATE and decision.match is not None:
        logger.info(
            "dedup DUPLICATE draft=%r → event_id=%s score=%.3f",
            draft.title[:60],
            decision.match.id,
            decision.score,
        )
        return decision, get_event(session, decision.match.id)

    if decision.action == DedupAction.UPDATE and decision.match is not None:
        payload = build_update_payload(decision.match, draft)
        updated = update_event(session, decision.match.id, payload)
        logger.info(
            "dedup UPDATE draft=%r → event_id=%s score=%.3f reason=%s",
            draft.title[:60],
            decision.match.id,
            decision.score,
            decision.reason,
        )
        return decision, updated

    created = create_event(session, to_event_create(draft))
    logger.debug("dedup NEW event_id=%s title=%r", created.id, created.title[:60])
    return DedupDecision(DedupAction.NEW, score=decision.score, reason=decision.reason), created
