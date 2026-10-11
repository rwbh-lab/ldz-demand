"""
UK gas-day aggregation for hourly gridded weather (ERA5 now, ECMWF ensemble later).

A gas day runs 05:00 to 05:00 UK local time (04:00 UTC during BST). Only complete gas days are
returned: 24 hours, or 23 / 25 for the gas days spanning the spring / autumn clock changes.
"""

import numpy as np
import pandas as pd
import xarray as xr

GAS_DAY_START_HOUR = 5  # UK local time
UK_TZ = "Europe/London"


def gas_day_labels(times) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """(gas day, UK local wall-clock time) for each UTC time."""
    utc = pd.DatetimeIndex(times).tz_localize("UTC")
    # Shift on the local wall clock (naive), not in absolute time, so 05:00 BST maps to its own day
    local = utc.tz_convert(UK_TZ).tz_localize(None)
    return (local - pd.Timedelta(hours=GAS_DAY_START_HOUR)).normalize(), local


def gas_day_slice(hourly: xr.Dataset, day) -> xr.Dataset:
    """The hours of one gas day, with a `local_time` coordinate (UK wall clock)."""
    gas_day, local = gas_day_labels(hourly["time"].values)
    keep = gas_day == pd.Timestamp(day)
    return hourly.isel(time=keep).assign_coords(local_time=("time", local[keep]))


def gas_day_means(hourly: xr.Dataset) -> xr.Dataset:
    """Mean of each variable over each complete gas day. Input dim `time` (UTC); output dim `gas_day`."""
    gas_day, _ = gas_day_labels(hourly["time"].values)
    labelled = hourly.assign_coords(gas_day=("time", gas_day))
    counts = pd.Series(1, index=gas_day).groupby(level=0).size()
    complete = counts.index[counts == gas_day_hours(counts.index)]
    daily = labelled.groupby("gas_day").mean("time")
    return daily.sel(gas_day=daily["gas_day"].isin(complete))


def gas_day_hours(gas_days: pd.DatetimeIndex) -> np.ndarray:
    """Real length in hours of each gas day: 24, or 23 / 25 across the clock changes."""
    starts = (gas_days + pd.Timedelta(hours=GAS_DAY_START_HOUR)).tz_localize(UK_TZ)
    ends = (gas_days + pd.Timedelta(days=1, hours=GAS_DAY_START_HOUR)).tz_localize(UK_TZ)
    return ((ends - starts) / pd.Timedelta(hours=1)).to_numpy().round().astype(int)
