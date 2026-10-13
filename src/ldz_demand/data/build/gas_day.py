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


def gas_day_bounds(gas_days) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """(start, end) of each gas day in UTC (naive): 05:00 UK local to 05:00 the next day."""
    days = pd.DatetimeIndex(gas_days).normalize()
    start = (days + pd.Timedelta(hours=GAS_DAY_START_HOUR)).tz_localize(UK_TZ).tz_convert("UTC").tz_localize(None)
    end = (days + pd.Timedelta(days=1, hours=GAS_DAY_START_HOUR)).tz_localize(UK_TZ).tz_convert("UTC").tz_localize(None)
    return start, end


def time_weights(times, gas_days) -> np.ndarray:
    """
    Hours of each gas day that each sample stands for: array [gas day, sample].

    The series is taken as a straight line between samples (linear interpolation), integrated over
    each gas day; a sample's weight is the integral of its share of that line. The first and last
    samples also stand flat for half their neighbouring gap beyond the ends of the series. With even
    spacing every interior sample gets the same weight; uneven spacing (forecast steps going from 3- to
    6-hourly) is handled exactly. Row sums are the hours of the gas day covered.
    """
    t = _hours(times)
    start, end = gas_day_bounds(gas_days)
    s, e = _hours(start)[:, None], _hours(end)[:, None]

    def overlap(lo, hi):  # length of [lo, hi] inside each gas day
        return np.clip(np.minimum(hi, e) - np.maximum(lo, s), 0, None)

    def ramp(a, b, rising):  # integral over each gas day of the line 0 -> 1 (rising) or 1 -> 0 on [a, b]
        lo, hi = np.maximum(a, s), np.minimum(b, e)
        lo, hi = np.minimum(lo, hi), hi
        width = np.where(b > a, b - a, 1.0)
        if rising:
            return ((hi - a) ** 2 - (lo - a) ** 2) / (2 * width) * (b > a)
        return ((b - lo) ** 2 - (b - hi) ** 2) / (2 * width) * (b > a)

    n = len(t)
    w = np.zeros((len(s), n))
    if n == 1:
        return overlap(t - 0.5, t + 0.5)
    w[:, 1:] += ramp(t[:-1], t[1:], rising=True)
    w[:, :-1] += ramp(t[:-1], t[1:], rising=False)
    w[:, 0] += overlap(np.array([t[0] - (t[1] - t[0]) / 2]), np.array([t[0]]))[:, 0]
    w[:, -1] += overlap(np.array([t[-1]]), np.array([t[-1] + (t[-1] - t[-2]) / 2]))[:, 0]
    return w


def _hours(times) -> np.ndarray:
    """Hours since the epoch, whatever the datetime unit."""
    return ((pd.DatetimeIndex(times) - pd.Timestamp(0)) / pd.Timedelta(hours=1)).to_numpy(dtype=float)


def gas_day_time_mean(values: np.ndarray, times, gas_days, method: str = "flat") -> tuple[np.ndarray, np.ndarray]:
    """
    Gas-day means of samples along the last axis of `values`: (means [..., gas day], hours covered [gas day]).

    method "flat" weights each sample by the time it stands for, interpolating linearly between
    samples (time_weights). Other methods, such as
    weighting by a within-day demand profile, slot in here once they are tested against demand.
    """
    if method != "flat":
        raise ValueError(f"unknown gas-day averaging method {method!r}")
    w = time_weights(times, gas_days)
    covered = w.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        means = (values @ w.T) / covered
    return means, covered


# Gas-day statistics per variable: (source variable, statistic). Accumulated variables (ssrd, tp) describe
# the hour ending at each time, so they are assigned to that hour, not to the instant it ends.
DAILY_STATS = {
    "t2m": ("t2m", "mean"),
    "ws10": ("ws10", "mean"),
    "tmin": ("t2m", "min"),
    "tmax": ("t2m", "max"),
    "ssrd": ("ssrd", "mean"),
    "tp": ("tp", "sum"),
}
INTERVAL_VARIABLES = {"ssrd", "tp"}


def gas_day_stats(hourly: xr.Dataset, stats: dict = DAILY_STATS) -> xr.Dataset:
    """
    Gas-day statistics of hourly data (dims time, ...; output dim gas_day): mean, min, max or sum,
    over complete gas days only. A gas day with any missing hour gets NaN, so sums are never partial.
    """
    out = {}
    complete_days = None
    for name, (source, stat) in stats.items():
        if source not in hourly:
            continue
        times = pd.DatetimeIndex(hourly["time"].values)
        if source in INTERVAL_VARIABLES:
            times = times - pd.Timedelta(hours=1)  # the hour ending at t starts at t - 1 h
        gas_day, _ = gas_day_labels(times)
        counts = pd.Series(1, index=gas_day).groupby(level=0).size()
        complete = counts.index[counts == gas_day_hours(counts.index)]
        grouped = hourly[source].assign_coords(gas_day=("time", gas_day)).groupby("gas_day")
        values = getattr(grouped, stat)("time", skipna=False)
        out[name] = values.sel(gas_day=values["gas_day"].isin(complete))
        complete_days = complete if complete_days is None else complete_days.union(complete)
    return xr.Dataset(out)


def interval_weights(times, gas_days) -> np.ndarray:
    """
    Hours of each gas day inside the period each sample describes, (previous sample, this sample]:
    array [gas day, sample]. For values that describe a period ending at the sample (accumulations,
    period extremes); the first sample, with no period, gets 0.
    """
    t = _hours(times)
    start, end = gas_day_bounds(gas_days)
    s, e = _hours(start)[:, None], _hours(end)[:, None]
    lo = np.concatenate([[t[0]], t[:-1]])
    return np.clip(np.minimum(t, e) - np.maximum(lo, s), 0, None)


def gas_day_interval_stat(values: np.ndarray, times, gas_days, stat: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Gas-day statistics of period values (each describing the time since the previous sample) along the
    last axis of `values`: (stat [..., gas day], hours covered [gas day]).

    mean: time-weighted mean of period means (e.g. W m-2); sum: each period's total pro rata to its hours
    in the gas day (e.g. mm); min / max: over the periods at least half inside the gas day.
    """
    w = interval_weights(times, gas_days)
    length = np.diff(_hours(times), prepend=_hours(times)[0])
    covered = w.sum(axis=1)
    v = np.nan_to_num(values, nan=0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        if stat == "mean":
            result = (v @ w.T) / covered
        elif stat == "sum":
            share = np.where(length > 0, w / np.where(length > 0, length, 1), 0)
            result = v @ share.T
        elif stat in ("min", "max"):
            inside = (w >= 0.5 * length) & (length > 0)            # [gas day, sample]
            masked = np.where(inside[(None,) * (values.ndim - 1)], values[..., None, :], np.nan)
            result = (np.nanmin if stat == "min" else np.nanmax)(masked, axis=-1)
        else:
            raise ValueError(f"unknown statistic {stat!r}")
    return result, covered
