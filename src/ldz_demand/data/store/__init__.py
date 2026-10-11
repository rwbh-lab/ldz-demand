"""Storage interface and implementations."""

import configparser

from ldz_demand.config import resolve_path, use_database
from ldz_demand.data.store.base import Dataset, Store, conform
from ldz_demand.data.store.csv_cache import CsvCacheStore

__all__ = ["CsvCacheStore", "Dataset", "Store", "conform", "get_store"]


def get_store(config: configparser.ConfigParser, store: Store | None = None) -> Store:
    """
    Store selected by config.

    - store given        -> returned as-is (tests, custom backends)
    - database = true    -> MySQLStore from LDZ_DB_* / .env (needs the db extra)
    - database = false   -> CsvCacheStore on cache_dir
    """
    if store is not None:
        return store
    if use_database(config):
        try:
            from ldz_demand.data.store.mysql import MySQLStore
        except ImportError as e:
            raise ImportError('database = true needs the db extra: pip install -e ".[db]"') from e
        return MySQLStore.from_env()
    return CsvCacheStore(resolve_path(config, "storage", "cache_dir"))
