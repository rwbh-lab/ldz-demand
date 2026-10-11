import configparser
from datetime import date

import pandas as pd
import pytest

from ldz_demand.data.store import CsvCacheStore, Dataset, get_store

DS = Dataset(
    "test_daily",
    columns={"gas_day": "date", "ldz": "str", "value": "float", "generated_time": "datetime"},
    keys=("gas_day", "ldz"),
)


def frame(rows):
    return pd.DataFrame(rows, columns=["gas_day", "ldz", "value", "generated_time"])


@pytest.fixture
def store(tmp_path):
    return CsvCacheStore(tmp_path / "cache")


def test_read_missing_dataset_is_empty_with_schema(store):
    df = store.read(DS)
    assert df.empty
    assert list(df.columns) == list(DS.columns)
    assert store.last_date(DS) is None


def test_round_trip_preserves_values_and_dtypes(store):
    rows = [("2026-01-01", "SE", 1.234567890123, "2026-01-02 06:00"), ("2026-01-02", "NW", None, None)]
    assert store.write(DS, frame(rows)) == 2

    df = store.read(DS)
    assert pd.api.types.is_datetime64_any_dtype(df["gas_day"])
    assert pd.api.types.is_datetime64_any_dtype(df["generated_time"])
    assert df.loc[df["ldz"] == "SE", "value"].item() == 1.234567890123
    assert df.loc[df["ldz"] == "NW", "value"].isna().item()


def test_skip_keeps_existing_rows(store):
    store.write(DS, frame([("2026-01-01", "SE", 1.0, None)]))
    written = store.write(DS, frame([("2026-01-01", "SE", 9.0, None), ("2026-01-02", "SE", 2.0, None)]))

    assert written == 1
    assert store.read(DS)["value"].tolist() == [1.0, 2.0]


def test_replace_overwrites_matching_keys(store):
    store.write(DS, frame([("2026-01-01", "SE", 1.0, None), ("2026-01-02", "SE", 2.0, None)]))
    written = store.write(DS, frame([("2026-01-01", "SE", 9.0, None)]), on_conflict="replace")

    assert written == 1
    assert store.read(DS)["value"].tolist() == [9.0, 2.0]


def test_read_filters_and_last_date(store):
    store.write(DS, frame([
        ("2026-01-01", "SE", 1.0, None),
        ("2026-01-02", "SE", 2.0, None),
        ("2026-01-03", "NW", 3.0, None),
    ]))

    assert store.read(DS, start="2026-01-02")["value"].tolist() == [2.0, 3.0]
    assert store.read(DS, end=date(2026, 1, 1))["value"].tolist() == [1.0]
    assert store.read(DS, ldz="SE")["value"].tolist() == [1.0, 2.0]
    assert store.read(DS, ldz=["NW"])["value"].tolist() == [3.0]
    assert store.last_date(DS, ldz="SE") == date(2026, 1, 2)
    with pytest.raises(ValueError, match="unknown filter column"):
        store.read(DS, region="SE")


def make_config(database: bool, cache_dir: str = "data/cache") -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read_dict({"storage": {"database": str(database).lower(), "cache_dir": cache_dir}})
    return config


def test_get_store_selects_backend(tmp_path):
    csv_store = get_store(make_config(False, str(tmp_path)))
    assert isinstance(csv_store, CsvCacheStore)
    assert csv_store.root == tmp_path

    db_store = object()
    assert get_store(make_config(True), database_store=db_store) is db_store
    with pytest.raises(RuntimeError, match="no database store"):
        get_store(make_config(True))
