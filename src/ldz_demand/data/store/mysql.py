"""
MySQL store — processed tables in a MySQL database (database = true).

Needs the db extra. Tables are created by migrations (python -m ldz_demand.db migrate), not here.
Writes run in one transaction per call, in chunks of multi-row INSERTs:
- skip    -> INSERT IGNORE (rows whose keys exist are left untouched)
- replace -> INSERT ... ON DUPLICATE KEY UPDATE (non-key columns overwritten)
"""

import logging
from datetime import date, datetime

import pandas as pd
import sqlalchemy as sa

from ldz_demand.data.store.base import Dataset, OnConflict, conform
from ldz_demand.db.connection import DbSettings, create_engine

logger = logging.getLogger(__name__)

CHUNK_ROWS = 500


class MySQLStore:
    """
    Store backed by MySQL.

    Parameters
    ----------
    engine : sqlalchemy.Engine
        Engine for the project database, e.g. from ldz_demand.db.connection.create_engine.
    """

    def __init__(self, engine: sa.Engine) -> None:
        self.engine = engine

    @classmethod
    def from_env(cls) -> "MySQLStore":
        return cls(create_engine(DbSettings.from_env()))

    def write(self, dataset: Dataset, df: pd.DataFrame, on_conflict: OnConflict = "skip") -> int:
        if on_conflict not in ("skip", "replace"):
            raise ValueError(f"on_conflict must be 'skip' or 'replace', got '{on_conflict}'")
        incoming = conform(dataset, df)
        if incoming.empty:
            return 0

        rows = _to_records(dataset, incoming)
        written = 0
        with self.engine.begin() as conn:
            for start in range(0, len(rows), CHUNK_ROWS):
                chunk = rows[start:start + CHUNK_ROWS]
                sql, params = _insert_sql(dataset, chunk, on_conflict)
                result = conn.execute(sa.text(sql), params)
                written += result.rowcount if on_conflict == "skip" else len(chunk)
        logger.info(f"{dataset.name}: wrote {written} of {len(incoming)} rows ({on_conflict})")
        return written

    def read(
        self,
        dataset: Dataset,
        start: date | str | None = None,
        end: date | str | None = None,
        **filters,
    ) -> pd.DataFrame:
        where, params, expanding = _where(dataset, start, end, filters)
        cols = ", ".join(f"`{c}`" for c in dataset.columns)
        order = ", ".join(f"`{k}`" for k in dataset.keys)
        query = sa.text(f"SELECT {cols} FROM `{dataset.name}`{where} ORDER BY {order}")
        if expanding:
            query = query.bindparams(*(sa.bindparam(name, expanding=True) for name in expanding))
        with self.engine.connect() as conn:
            df = pd.read_sql(query, conn, params=params)
        return conform(dataset, df)

    def last_date(self, dataset: Dataset, **filters) -> date | None:
        where, params, expanding = _where(dataset, None, None, filters)
        query = sa.text(f"SELECT MAX(`{dataset.date_col}`) FROM `{dataset.name}`{where}")
        if expanding:
            query = query.bindparams(*(sa.bindparam(name, expanding=True) for name in expanding))
        with self.engine.connect() as conn:
            value = conn.execute(query, params).scalar()
        if value is None:
            return None
        return value.date() if isinstance(value, datetime) else value


def _to_records(dataset: Dataset, df: pd.DataFrame) -> list[dict]:
    """Rows as dicts of plain Python values, with NA as None."""
    columns = {}
    for col, dtype in dataset.columns.items():
        s = df[col]
        if dtype == "date":
            values = [None if pd.isna(v) else v.date() for v in s]
        elif dtype == "datetime":
            values = [None if pd.isna(v) else v.to_pydatetime() for v in s]
        elif dtype == "float":
            values = [None if pd.isna(v) else float(v) for v in s]
        elif dtype == "int":
            values = [None if pd.isna(v) else int(v) for v in s]
        else:
            values = [None if pd.isna(v) else str(v) for v in s]
        columns[col] = values
    return [dict(zip(columns, row)) for row in zip(*columns.values())]


def _insert_sql(dataset: Dataset, rows: list[dict], on_conflict: OnConflict) -> tuple[str, dict]:
    """One multi-row INSERT for rows, with uniquely named bind parameters."""
    cols = list(dataset.columns)
    params, values = {}, []
    for i, row in enumerate(rows):
        names = []
        for j, col in enumerate(cols):
            name = f"p{i}_{j}"
            params[name] = row[col]
            names.append(f":{name}")
        values.append(f"({', '.join(names)})")

    col_list = ", ".join(f"`{c}`" for c in cols)
    verb = "INSERT IGNORE" if on_conflict == "skip" else "INSERT"
    sql = f"{verb} INTO `{dataset.name}` ({col_list}) VALUES {', '.join(values)}"
    if on_conflict == "replace":
        updates = [c for c in cols if c not in dataset.keys] or [dataset.keys[0]]
        sql += " AS new ON DUPLICATE KEY UPDATE " + ", ".join(f"`{c}` = new.`{c}`" for c in updates)
    return sql, params


def _where(dataset: Dataset, start, end, filters: dict) -> tuple[str, dict, list[str]]:
    """WHERE clause, bind params, and names of list-valued (expanding) params."""
    clauses, params, expanding = [], {}, []
    if start is not None:
        clauses.append(f"`{dataset.date_col}` >= :start")
        params["start"] = _bound_date(dataset, start)
    if end is not None:
        clauses.append(f"`{dataset.date_col}` <= :end")
        params["end"] = _bound_date(dataset, end)
    for col, value in filters.items():
        if col not in dataset.columns:
            raise ValueError(f"{dataset.name}: unknown filter column '{col}'")
        name = f"f_{col}"
        if isinstance(value, (list, tuple, set)):
            clauses.append(f"`{col}` IN :{name}")
            params[name] = list(value)
            expanding.append(name)
        else:
            clauses.append(f"`{col}` = :{name}")
            params[name] = value
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params, expanding


def _bound_date(dataset: Dataset, value) -> date | datetime:
    ts = pd.Timestamp(value)
    return ts.date() if dataset.columns[dataset.date_col] == "date" else ts.to_pydatetime()
