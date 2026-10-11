"""Store factory. Backend behaviour is covered by test_store_contract.py."""

import configparser

import pytest

from ldz_demand.data.store import CsvCacheStore, get_store


def make_config(database: bool, cache_dir: str = "data/cache") -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read_dict({"storage": {"database": str(database).lower(), "cache_dir": cache_dir}})
    return config


def test_get_store_csv_by_default(tmp_path):
    store = get_store(make_config(False, str(tmp_path)))
    assert isinstance(store, CsvCacheStore)
    assert store.root == tmp_path


def test_get_store_explicit_store_wins():
    custom = object()
    assert get_store(make_config(True), store=custom) is custom
    assert get_store(make_config(False), store=custom) is custom


def test_get_store_database_builds_mysql_store(monkeypatch):
    pytest.importorskip("sqlalchemy")
    from ldz_demand.data.store.mysql import MySQLStore

    for key in ("LDZ_DB_HOST_LOCAL", "LDZ_DB_HOST_REMOTE", "LDZ_DB_NETWORK", "LDZ_DB_HOME_GATEWAY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("ldz_demand.db.connection.load_env", lambda: None)
    monkeypatch.setenv("LDZ_DB_HOST", "db.example")
    monkeypatch.setenv("LDZ_DB_NAME", "ldz_demand")
    monkeypatch.setenv("LDZ_DB_USER", "ldz_app")
    monkeypatch.setenv("LDZ_DB_PASSWORD", "not-a-real-password")

    store = get_store(make_config(True))
    assert isinstance(store, MySQLStore)
    assert store.engine.url.host == "db.example"  # engine is lazy: nothing connected
