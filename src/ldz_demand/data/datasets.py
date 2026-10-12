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
        "unit": "str",                # mcm, kWh, MJ/m3, degC — items are NOT all in the same unit
        "quality": "str",             # Quality Indicator
        "applicable_at": "datetime",  # Applicable At (publication time)
        "generated_time": "datetime",
    },
    keys=("gas_day", "ldz", "item"),
)

NG_OFFTAKE_DAILY = Dataset(
    "ng_offtake_daily",
    columns={
        "gas_day": "date",
        "ldz": "str",
        "site": "str",                # NTS offtake point, e.g. Farningham
        "data_item_id": "str",        # National Gas PUBOBJ id
        "value": "float",
        "unit": "str",                # kWh
        "quality": "str",
        "applicable_at": "datetime",
        "generated_time": "datetime",
    },
    keys=("gas_day", "ldz", "site"),
)

WEATHER_LDZ_DAILY = Dataset(
    "weather_ldz_daily",
    columns={
        "gas_day": "date",
        "ldz": "str",
        "membership": "str",          # map method: authority, voronoi, hybrid, sampled; or station
        "weighting": "str",           # area, gas; or point (station)
        "variable": "str",            # t2m, ws10
        "value": "float",
        "unit": "str",                # degC, m s-1
        "source": "str",              # era5 (final) or era5t (preliminary)
    },
    keys=("gas_day", "ldz", "membership", "weighting", "variable"),
)

DATASETS: dict[str, Dataset] = {ds.name: ds for ds in (NG_LDZ_DAILY, NG_OFFTAKE_DAILY, WEATHER_LDZ_DAILY)}
