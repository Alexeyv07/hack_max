from address.street_catalog import StreetCatalog
from chat_link.handlers import cache


def test_address_snapshot_is_reused_without_new_db_session(monkeypatch) -> None:
    snapshot = StreetCatalog([])
    monkeypatch.setattr(cache, "_catalog", snapshot)

    def fail_session_scope():
        raise AssertionError("SQL не должен выполняться после прогрева StreetCatalog")

    monkeypatch.setattr(cache, "session_scope", fail_session_scope)
    assert cache.get_address_catalog() is snapshot
