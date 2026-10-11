"""
Store interface.

Ingestors and loaders talk only to this interface. Implementations:
- CsvCacheStore — default, database = false. Processed tables as CSV in cache_dir.
- MySQLStore    — database = true. Optional install (ldz-demand[db]); credentials from environment.

A Dataset describes one processed table (name, columns, natural key) and is the single schema
both backends work from. Raw downloads are not stored here — they always go to raw_dir as files.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

import pandas as pd

logger = logging.getLogger(__name__)

DTYPES = ("date", "datetime", "str", "float", "int")

# Table and column names are used directly in SQL, so they are restricted to safe identifiers
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}")

OnConflict = Literal["skip", "replace"]


@dataclass(frozen=True)
class Dataset:
    """
    Schema for one processed table.

    Parameters
    ----------
    name : str
        CSV file stem / database table name.
    columns : dict[str, str]
        Column name -> dtype, one of DTYPES. Order is the stored column order.
    keys : tuple[str, ...]
        Natural primary key. Rows are unique on these columns.
    date_col : str
        Column used for start/end filtering and last_date.
    """

    name: str
    columns: dict[str, str]
    keys: tuple[str, ...]
    date_col: str = "gas_day"

    def __post_init__(self) -> None:
        bad_names = [n for n in (self.name, *self.columns) if not IDENTIFIER.fullmatch(n)]
        if bad_names:
            raise ValueError(f"{self.name}: names must be lower_snake_case identifiers, got {bad_names}")
        bad_dtypes = {c: t for c, t in self.columns.items() if t not in DTYPES}
        if bad_dtypes:
            raise ValueError(f"{self.name}: unknown dtypes {bad_dtypes}; expected one of {DTYPES}")
        missing = [c for c in (*self.keys, self.date_col) if c not in self.columns]
        if missing:
            raise ValueError(f"{self.name}: key/date columns {missing} not in columns")


class Store(Protocol):
    """Storage backend for processed tables."""

    def write(self, dataset: Dataset, df: pd.DataFrame, on_conflict: OnConflict = "skip") -> int:
        """
        Write rows. on_conflict="skip" keeps existing rows whose keys match; "replace" overwrites them.
        Returns the number of rows written.
        """
        ...

    def read(
        self,
        dataset: Dataset,
        start: date | str | None = None,
        end: date | str | None = None,
        **filters,
    ) -> pd.DataFrame:
        """Read rows with date_col in [start, end] (inclusive), filtered on column=value pairs."""
        ...

    def last_date(self, dataset: Dataset, **filters) -> date | None:
        """Latest date_col value stored (after filters), or None if there are no rows."""
        ...


def conform(dataset: Dataset, df: pd.DataFrame) -> pd.DataFrame:
    """
    Check and coerce a frame to the dataset schema before writing.

    Selects and orders the schema columns, coerces dtypes, and checks the key columns are
    non-null and unique. Shared by all backends so they store identical data.
    """
    missing = [c for c in dataset.columns if c not in df.columns]
    if missing:
        raise ValueError(f"{dataset.name}: missing columns {missing}")

    out = df[list(dataset.columns)].copy()
    for col, dtype in dataset.columns.items():
        out[col] = _coerce(out[col], dtype)

    null_keys = out[list(dataset.keys)].isna().any(axis=1)
    if null_keys.any():
        raise ValueError(f"{dataset.name}: {null_keys.sum()} rows with null key columns")
    duplicated = out.duplicated(subset=list(dataset.keys))
    if duplicated.any():
        raise ValueError(f"{dataset.name}: {duplicated.sum()} rows with duplicate keys {dataset.keys}")

    return out.reset_index(drop=True)


def _coerce(series: pd.Series, dtype: str) -> pd.Series:
    if dtype == "date":
        return pd.to_datetime(series).dt.normalize()
    if dtype == "datetime":
        return pd.to_datetime(series)
    if dtype == "str":
        return series.astype("string")
    if dtype == "float":
        return pd.to_numeric(series).astype("float64")
    if dtype == "int":
        return pd.to_numeric(series).astype("Int64")
    raise ValueError(f"Unknown dtype '{dtype}'")
