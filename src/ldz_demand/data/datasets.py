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

WEATHER_LDZ_HOURLY = Dataset(
    "weather_ldz_hourly",
    columns={
        "time": "datetime",           # UTC, the ERA5 hour
        "ldz": "str",
        "membership": "str",          # only the [ldz_weather] detail_variants
        "weighting": "str",
        "variable": "str",            # t2m, ws10
        "value": "float",
        "unit": "str",
        "source": "str",              # era5 or era5t
    },
    keys=("time", "ldz", "membership", "weighting", "variable"),
    date_col="time",
)

ENS_LDZ_DAILY = Dataset(
    "ens_ldz_daily",
    columns={
        "run_date": "date",           # date of the forecast run
        "run_hour": "int",            # UTC hour of the run (0)
        "member": "int",              # ensemble member, 1-50
        "gas_day": "date",
        "lead_days": "int",           # gas_day - run_date: 0 (the run's own gas day) to 14
        "ldz": "str",
        "membership": "str",          # only the [ldz_weather] detail_variants
        "weighting": "str",
        "variable": "str",            # t2m, ws10
        "method": "str",              # gas-day averaging: flat (time-weighted)
        "value": "float",
        "unit": "str",
        "coverage_h": "float",        # hours of the gas day the forecast steps cover (23-25 when complete)
    },
    keys=("run_date", "run_hour", "member", "gas_day", "ldz", "membership", "weighting", "variable", "method"),
    date_col="run_date",
)

NG_FORECAST_DAILY = Dataset(
    "ng_forecast_daily",
    columns={
        "gas_day": "date",            # Applicable For: the gas day forecast
        "ldz": "str",
        "item": "str",                # demand_forecast, cwv_forecast_d, cwv_forecast_d_minus_1
        "issued_at": "datetime",      # Applicable At: when this issue was made (UK time)
        "issue_day": "int",           # calendar date of issue minus gas day: -1 (day ahead) or 0 (within day)
        "data_item_id": "str",
        "value": "float",
        "unit": "str",                # mcm (demand), degC (CWV)
        "quality": "str",
        "generated_time": "datetime",
    },
    keys=("gas_day", "ldz", "item", "issued_at"),
)

DEMAND_FORECAST_DAILY = Dataset(
    "demand_forecast_daily",
    columns={
        "run_date": "date",           # date of the ensemble run
        "run_hour": "int",            # UTC hour of the run (0)
        "gas_day": "date",
        "lead_days": "int",           # gas_day - run_date: 0 to 13
        "ldz": "str",                 # an LDZ, or GB (their sum, member by member)
        "statistic": "str",           # mean; p05 ... p95 (weather and model error); weather_p10 / weather_p90
        "value": "float",
        "unit": "str",                # GWh/day, total - DM (the model's target)
        "model": "str",               # the fit used: models/data/final_fit.csv "fitted_on" date
    },
    keys=("run_date", "run_hour", "gas_day", "ldz", "statistic"),
    date_col="run_date",
)

DATASETS: dict[str, Dataset] = {
    ds.name: ds for ds in (NG_LDZ_DAILY, NG_OFFTAKE_DAILY, WEATHER_LDZ_DAILY, WEATHER_LDZ_HOURLY, ENS_LDZ_DAILY,
                           NG_FORECAST_DAILY, DEMAND_FORECAST_DAILY)
}
