"""RawChatMessage → ParserCandidate → events через parser_common."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from address.street_catalog import StreetCatalog
from events.handlers.crud import list_existing_source_msg_ids
from events.models.event import Event, EventSource
from ml_dedup.resolve import resolve_draft
from parse_chat.models.message import RawChatMessage
from parser_common.models.candidate import ParserCandidate
from parser_common.normalize import normalize
from project.logging_setup import get_logger
from user_chat.db.chat import ChatRow

logger = get_logger(__name__)

_street_catalog: StreetCatalog | None = None


def _get_street_catalog(session: Session) -> StreetCatalog | None:
    global _street_catalog
    if _street_catalog is not None:
        return _street_catalog
    try:
        _street_catalog = StreetCatalog.load(session, city="Москва")
    except Exception:
        logger.exception("StreetCatalog.load failed")
        return None
    return _street_catalog


def make_source_msg_id(chat_id: int, message_id: str) -> str:
    """Идемпотентный ключ: chat + mid (mid глобально уникален, chat — для читаемости)."""
    return f"{chat_id}:{message_id}"


def geo_by_for_address(address: AddressRow) -> str:
    if address.house:
        return "home"
    if address.street:
        return "street"
    return "city"


def message_to_candidate(message: RawChatMessage) -> ParserCandidate:
    """Без address_id: сначала place NER / StreetCatalog, иначе fallback на чат."""
    text = (message.text or "").strip()
    if not text and message.image_url:
        text = "Фото из чата соседей"
    return ParserCandidate(
        raw_text=text,
        source=EventSource.NEIGHBORS_CHAT.value,
        source_msg_id=make_source_msg_id(message.chat_id, message.message_id),
        source_url=message.source_url,
        image_url=message.image_url,
        geo_text=text,
        published_at=message.published_at,
    )


def load_active_chat_row(session: Session, chat_id: int) -> ChatRow | None:
    """Любой подключённый домовой чат соседей (chat_type='chat')."""
    row = session.get(ChatRow, chat_id)
    if row is None or row.chat_type != "chat":
        return None
    return row


def persist_chat_message(
    session: Session,
    message: RawChatMessage,
    *,
    chat: ChatRow | None = None,
) -> Event | None:
    """
    Записать прошедшее фильтр сообщение в events.

    Гео: spaCy / StreetCatalog по тексту; если не вышло — адрес чата.
    Time: всегда ONNX. Classify / dedup — в normalize / resolve_draft.
    """
    chat_row = chat if chat is not None else load_active_chat_row(session, message.chat_id)
    if chat_row is None:
        logger.debug("parse_chat: чат %s не подключён — пропуск", message.chat_id)
        return None

    address = chat_row.address
    if address is None:
        address = session.get(AddressRow, chat_row.address_id)
    if address is None:
        logger.warning(
            "parse_chat: у чата %s нет address_id=%s",
            message.chat_id,
            chat_row.address_id,
        )
        return None

    source_msg_id = make_source_msg_id(message.chat_id, message.message_id)
    existing = list_existing_source_msg_ids(
        session,
        source=EventSource.NEIGHBORS_CHAT.value,
        source_msg_ids=[source_msg_id],
    )
    if source_msg_id in existing:
        logger.debug("parse_chat: дубликат %s — пропуск", source_msg_id)
        return None

    candidate = message_to_candidate(message)
    coords: tuple[Decimal, Decimal] = (address.latitude, address.longitude)
    fallback_geo = geo_by_for_address(address)

    try:
        with session.begin_nested():
            catalog = _get_street_catalog(session)
            draft = normalize(
                candidate,
                street_catalog=catalog,
                chat_coordinates=coords,
            )
            if draft.address_id is None:
                draft = replace(
                    draft,
                    address_id=address.id,
                    geo_by=fallback_geo,
                    geo_method="chat_fallback",
                    geo_scope=fallback_geo,
                )
                logger.debug(
                    "parse_chat geo chat_fallback address_id=%s geo_by=%s",
                    address.id,
                    fallback_geo,
                )
            else:
                logger.debug(
                    "parse_chat geo from text address_id=%s geo_by=%s method=%s",
                    draft.address_id,
                    draft.geo_by,
                    draft.geo_method,
                )

            _decision, event = resolve_draft(session, draft)
            return event
    except IntegrityError:
        logger.debug("parse_chat: IntegrityError %s — пропуск", source_msg_id)
        return None
