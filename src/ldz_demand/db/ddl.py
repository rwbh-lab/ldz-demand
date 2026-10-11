"""
MySQL DDL from Dataset definitions.

create_table_sql drafts a CREATE TABLE for a new migration file (python -m ldz_demand.db draft <name>);
the committed migration file, not this output, is the source of truth.
"""

from ldz_demand.data.store.base import Dataset

MYSQL_TYPES = {
    "date": "DATE",
    "datetime": "DATETIME",
    "str": "VARCHAR(64)",
    "float": "DOUBLE",
    "int": "BIGINT",
}

# information_schema DATA_TYPE for each dtype — used by the schema drift check
INFO_SCHEMA_TYPES = {
    "date": "date",
    "datetime": "datetime",
    "str": "varchar",
    "float": "double",
    "int": "bigint",
}


def create_table_sql(dataset: Dataset) -> str:
    lines = []
    for col, dtype in dataset.columns.items():
        null = "NOT NULL" if col in dataset.keys else "NULL"
        lines.append(f"  `{col}` {MYSQL_TYPES[dtype]} {null}")
    lines.append(f"  PRIMARY KEY ({', '.join(f'`{k}`' for k in dataset.keys)})")
    if dataset.date_col != dataset.keys[0]:
        lines.append(f"  KEY `idx_{dataset.name}_{dataset.date_col}` (`{dataset.date_col}`)")
    body = ",\n".join(lines)
    return (
        f"CREATE TABLE IF NOT EXISTS `{dataset.name}` (\n{body}\n"
        f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;\n"
    )
