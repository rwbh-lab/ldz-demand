"""
Processed table definitions — the single schema shared by the CSV cache and MySQL.

Changing a Dataset that already exists in a database needs a new migration in db/migrations/;
the schema drift test checks the migrated tables still match these definitions.
"""

from ldz_demand.data.store.base import Dataset

NG_LDZ_DAILY = Dataset(
    "ng_ldz_daily",
    columns={
        "gas_day": "date",            # Applicable For
        "ldz": "str",                 # EA, EM, ..., WS
        "item": "str",                # e.g. demand_total_d6, demand_dm_d6, cwv_actual
        "data_item_id": "str",        # National Gas PUBOB id
        "value": "float",
        "quality": "str",             # Quality Indicator
        "applicable_at": "datetime",  # Applicable At (publication time)
        "generated_time": "datetime",
    },
    keys=("gas_day", "ldz", "item"),
)

DATASETS: dict[str, Dataset] = {ds.name: ds for ds in (NG_LDZ_DAILY,)}
