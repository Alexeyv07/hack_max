"""KAN-19 ml_dedup — runtime дедуп / актуализация Events.

Обучение и пороги: ``ml/dedup/`` (вне src).

```
EventDraft ──resolve_draft──▶ NEW | DUPLICATE | UPDATE
                                │       │          │
                           create_event  noop   update_event
```

Окно активности: ``ml_dedup.active_days`` (дефолт 21) — новость недельной
давности всё ещё матчится, если не истекла по ``active_to``.
"""

from __future__ import annotations

# re-export
from ml_dedup.active import is_event_active, list_active_events
from ml_dedup.models import ActiveEventView
from ml_dedup.resolve import DedupAction, DedupConfig, DedupDecision, resolve_draft

__all__ = [
    "ActiveEventView",
    "DedupAction",
    "DedupConfig",
    "DedupDecision",
    "is_event_active",
    "list_active_events",
    "resolve_draft",
]
