"""
CSV cache store — processed tables as one CSV per dataset in cache_dir.

The default backend (database = false): no setup, suits one-off use of the repo. Each write loads
the existing file, merges on the dataset keys, and rewrites it atomically. Fine for the table sizes
here (~10^5 rows); larger datasets would want partitioned files.
"""

import logging
import os
from datetime import date
from pathlib import Path

import pandas as pd

from ldz_demand.data.store.base import Dataset, OnConflict, conform

logger = logging.getLogger(__name__)

DATE_FORMATS = {"date": "%Y-%m-%d", "datetime": "%Y-%m-%d %H:%M:%S"}


class CsvCacheStore:
    """
    Store backed by CSV files.

    Parameters
    ----------
    root : Path
        Cache directory; created on first write. Dataset `name` is stored at root / f"{name}.csv".
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, dataset: Dataset) -> Path:
        return self.root / f"{dataset.name}.csv"

    def write(self, dataset: Dataset, df: pd.DataFrame, on_conflict: OnConflict = "skip") -> int:
        incoming = conform(dataset, df)
        existing = self._load(dataset)
        keys = list(dataset.keys)

        if on_conflict == "skip":
            new = _anti_join(incoming, existing, keys)
            combined = pd.concat([existing, new], ignore_index=True)
            written = len(new)
        elif on_conflict == "replace":
            kept = _anti_join(existing, incoming, keys)
            combined = pd.concat([kept, incoming], ignore_index=True)
            written = len(incoming)
        else:
            raise ValueError(f"on_conflict must be 'skip' or 'replace', got '{on_conflict}'")

        if written:
            self._save(dataset, combined.sort_values(keys, ignore_index=True))
        logger.info(f"{dataset.name}: wrote {written} of {len(incoming)} rows ({on_conflict})")
        return written

    def read(
        self,
        dataset: Dataset,
        start: date | str | None = None,
        end: date | str | None = None,
        **filters,
    ) -> pd.DataFrame:
        df = self._load(dataset)
        mask = pd.Series(True, index=df.index)
        if start is not None:
            mask &= df[dataset.date_col] >= pd.Timestamp(start)
        if end is not None:
            mask &= df[dataset.date_col] <= pd.Timestamp(end)
        for col, value in filters.items():
            if col not in dataset.columns:
                raise ValueError(f"{dataset.name}: unknown filter column '{col}'")
            if isinstance(value, (list, tuple, set)):
                mask &= df[col].isin(list(value))
            else:
                mask &= df[col] == value
        return df[mask].reset_index(drop=True)

    def last_date(self, dataset: Dataset, **filters) -> date | None:
        dates = self.read(dataset, **filters)[dataset.date_col]
        return None if dates.empty else dates.max().date()

    def _load(self, dataset: Dataset) -> pd.DataFrame:
        path = self.path(dataset)
        if not path.exists():
            return conform(dataset, pd.DataFrame(columns=list(dataset.columns)))
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
        for col, dtype in dataset.columns.items():
            if dtype in ("date", "datetime"):
                # ISO8601 also reads files written before formats were fixed (mixed date / datetime)
                df[col] = pd.to_datetime(df[col], format="ISO8601")
        return conform(dataset, df)

    def _save(self, dataset: Dataset, df: pd.DataFrame) -> None:
        path = self.path(dataset)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".csv.tmp")
        _format_dates(dataset, df).to_csv(tmp, index=False)
        os.replace(tmp, path)


def _format_dates(dataset: Dataset, df: pd.DataFrame) -> pd.DataFrame:
    """
    Write dates and datetimes in one fixed format each. Left to pandas, to_csv picks the format per
    chunk of rows (date-only when every time in the chunk is midnight), which mixes formats in one file.
    """
    out = df.copy()
    for col, dtype in dataset.columns.items():
        if dtype in ("date", "datetime"):
            out[col] = out[col].dt.strftime(DATE_FORMATS[dtype])
    return out


def _anti_join(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Rows of left whose keys are not in right."""
    if right.empty or left.empty:
        return left
    merged = left.merge(right[keys], on=keys, how="left", indicator=True)
    return left[(merged["_merge"] == "left_only").to_numpy()]
