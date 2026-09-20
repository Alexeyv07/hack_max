from __future__ import annotations

from threading import Lock

from address.street_catalog import StreetCatalog
from project.database import session_scope

_catalog: StreetCatalog | None = None
_lock = Lock()


def get_address_catalog(*, refresh: bool = False) -> StreetCatalog:
    """Общий process-wide snapshot существующего address.StreetCatalog."""
    global _catalog
    if _catalog is not None and not refresh:
        return _catalog
    with _lock:
        if _catalog is None or refresh:
            with session_scope() as session:
                _catalog = StreetCatalog.load(session, city=None)
    return _catalog
