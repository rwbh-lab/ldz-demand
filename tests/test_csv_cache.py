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


def test_large_tables_keep_one_datetime_format(tmp_path):
    """Regression: pandas chunks big CSV writes and picked a date-only format for all-midnight chunks."""
    import pandas as pd

    from ldz_demand.data.store import Dataset

    ds = Dataset("big", columns={"gas_day": "date", "seq": "int", "stamp": "datetime"}, keys=("gas_day", "seq"))
    n = 250_000
    stamps = pd.Series(pd.Timestamp("2026-01-01"), index=range(n))
    stamps.iloc[-10:] = pd.Timestamp("2026-01-01 12:30:00")  # only the last chunk has non-midnight times
    df = pd.DataFrame({"gas_day": pd.Timestamp("2026-01-01"), "seq": range(n), "stamp": stamps})
    store = CsvCacheStore(tmp_path)
    store.write(ds, df)

    back = store.read(ds)
    assert len(back) == n
    assert back["stamp"].iloc[-1] == pd.Timestamp("2026-01-01 12:30:00")
    assert back["stamp"].iloc[0] == pd.Timestamp("2026-01-01")
