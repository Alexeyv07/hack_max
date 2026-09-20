"""KAN-19 ml_dedup — runtime дедуп / актуализация Events.

Обучение и пороги: ``ml/dedup/`` (вне src).

```
EventDraft ──resolve_draft──▶ NEW | DUPLICATE | UPDATE
                                │       │          │
                           create_event  noop   update_event
```

Окно активности: ``ml_dedup.active_days`` (дефолт 21).
"""

from __future__ import annotations

from ml_dedup.active import is_event_active, list_active_events
from ml_dedup.models import ActiveEventView

__all__ = [
    "ActiveEventView",
    "DedupAction",
    "DedupConfig",
    "DedupDecision",
    "is_event_active",
    "list_active_events",
    "resolve_draft",
]


def __getattr__(name: str):
    # Lazy: избегаем цикла ml_dedup ↔ parser_common при import embed/тестов.
    if name in {"DedupAction", "DedupConfig", "DedupDecision", "resolve_draft"}:
        from ml_dedup import resolve as _resolve

        return getattr(_resolve, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
