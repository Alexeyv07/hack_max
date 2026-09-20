"""In-memory очередь кандидатов между парсерами и normalize/dedup.

Потеря при падении процесса допустима (продуктовое решение хакатона).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from parser_common.models.candidate import ParserCandidate
from project.logging_setup import get_logger

logger = get_logger(__name__)

CandidateHandler = Callable[[ParserCandidate], Awaitable[None] | None]


@dataclass
class CandidateQueue:
    """asyncio.Queue-обёртка с drop-on-full."""

    maxsize: int = 500
    dropped: int = 0
    enqueued: int = 0
    processed: int = 0
    _queue: asyncio.Queue[ParserCandidate] | None = field(default=None, repr=False)

    def _ensure(self) -> asyncio.Queue[ParserCandidate]:
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self.maxsize)
        return self._queue

    def put_nowait(self, candidate: ParserCandidate) -> bool:
        q = self._ensure()
        try:
            q.put_nowait(candidate)
            self.enqueued += 1
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning(
                "candidate queue full (max=%s) — drop source=%s msg=%s",
                self.maxsize,
                candidate.source,
                candidate.source_msg_id,
            )
            return False

    async def put(self, candidate: ParserCandidate) -> bool:
        return self.put_nowait(candidate)

    async def run_consumer(
        self,
        handler: CandidateHandler,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        q = self._ensure()
        while True:
            if stop_event is not None and stop_event.is_set() and q.empty():
                return
            try:
                candidate = await asyncio.wait_for(q.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                result = handler(candidate)
                if isinstance(result, Awaitable):
                    await result
                self.processed += 1
            except Exception:
                logger.exception(
                    "candidate consumer failed source=%s msg=%s",
                    candidate.source,
                    candidate.source_msg_id,
                )
            finally:
                q.task_done()


_GLOBAL: CandidateQueue | None = None


def get_candidate_queue(*, maxsize: int = 500) -> CandidateQueue:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = CandidateQueue(maxsize=maxsize)
    return _GLOBAL
