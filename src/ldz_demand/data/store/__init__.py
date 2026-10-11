"""Storage interface and implementations."""

import configparser

from ldz_demand.config import resolve_path, use_database
from ldz_demand.data.store.base import Dataset, Store, conform
from ldz_demand.data.store.csv_cache import CsvCacheStore

__all__ = ["CsvCacheStore", "Dataset", "Store", "conform", "get_store"]


def get_store(config: configparser.ConfigParser, database_store: Store | None = None) -> Store:
    """
    Store selected by config: the supplied database store when database = true, else the CSV cache.
    """
    if use_database(config):
        if database_store is None:
            raise RuntimeError("Config has database = true but no database store was supplied")
        return database_store
    return CsvCacheStore(resolve_path(config, "storage", "cache_dir"))
