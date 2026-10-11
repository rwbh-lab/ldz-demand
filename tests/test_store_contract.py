"""Behaviour every Store backend must share. Each test runs against the CSV cache and MySQL."""

from datetime import date

import pandas as pd
import pytest

from ldz_demand.data.store import CsvCacheStore, Dataset

DS = Dataset(
    "test_daily",
    columns={"gas_day": "date", "ldz": "str", "value": "float", "generated_time": "datetime"},
    keys=("gas_day", "ldz"),
)


def frame(rows):
    return pd.DataFrame(rows, columns=["gas_day", "ldz", "value", "generated_time"])


@pytest.fixture(params=["csv", "mysql"])
def store(request, tmp_path):
    if request.param == "csv":
        return CsvCacheStore(tmp_path / "cache")

    import sqlalchemy as sa

    from conftest import drop_all_tables
    from ldz_demand.data.store.mysql import MySQLStore
    from ldz_demand.db.ddl import create_table_sql

    engine = request.getfixturevalue("mysql_engine")
    drop_all_tables(engine)
    with engine.begin() as conn:
        conn.execute(sa.text(create_table_sql(DS)))
    return MySQLStore(engine)


def test_read_empty_dataset_has_schema(store):
    df = store.read(DS)
    assert df.empty
    assert list(df.columns) == list(DS.columns)
    assert store.last_date(DS) is None


def test_round_trip_preserves_values_and_dtypes(store):
    rows = [("2026-01-01", "SE", 1.234567890123, "2026-01-02 06:00:05"), ("2026-01-02", "NW", None, None)]
    assert store.write(DS, frame(rows)) == 2

    df = store.read(DS)
    assert pd.api.types.is_datetime64_any_dtype(df["gas_day"])
    assert pd.api.types.is_datetime64_any_dtype(df["generated_time"])
    se = df[df["ldz"] == "SE"].iloc[0]
    assert se["value"] == 1.234567890123
    assert se["generated_time"] == pd.Timestamp("2026-01-02 06:00:05")
    assert df.loc[df["ldz"] == "NW", "value"].isna().item()
    assert df.loc[df["ldz"] == "NW", "generated_time"].isna().item()


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


def test_write_many_rows_across_chunks(store):
    days = pd.date_range("2020-01-01", periods=1200, freq="D")
    df = frame([(d, "SE", float(i), None) for i, d in enumerate(days)])

    assert store.write(DS, df) == 1200
    assert store.write(DS, df) == 0
    assert len(store.read(DS)) == 1200
    assert store.last_date(DS) == days[-1].date()


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
    assert store.last_date(DS, ldz="WS") is None
    with pytest.raises(ValueError, match="unknown filter column"):
        store.read(DS, region="SE")


def test_write_rejects_bad_on_conflict(store):
    with pytest.raises(ValueError, match="on_conflict"):
        store.write(DS, frame([("2026-01-01", "SE", 1.0, None)]), on_conflict="upsert")
