"""
Ways of averaging hourly temperature into a gas-day value (experiment 5; docs/methodology.md §5.4).

The daily tables use a flat time-weighted mean. Gas use isn't flat through the day — heating peaks in
the morning and evening — so a mean weighted towards those hours might track demand better:

- "flat":  every hour of the gas day counts the same;
- "peaks": 06–09 and 16–22 UK time count double, 23–05 half (a typical domestic heating day).

step_hours=3 first thins the hourly series to every third UTC hour and interpolates back, as the
ECMWF ensemble only gives 3-hourly steps (6-hourly after day 6): it shows how much of any gain would
survive in forecasting.
"""

import numpy as np
import pandas as pd

from ldz_demand.data.build.gas_day import gas_day_labels

PROFILES = ("flat", "peaks")
MIN_HOURS = 23  # a gas day is 23, 24 or 25 hours (clock changes); fewer means missing data


def hour_weights(local_hour: np.ndarray, profile: str) -> np.ndarray:
    """Weight per hour, by its UK local starting hour."""
    if profile == "flat":
        return np.ones(len(local_hour))
    peak = ((local_hour >= 6) & (local_hour < 9)) | ((local_hour >= 16) & (local_hour < 22))
    night = (local_hour >= 23) | (local_hour < 5)
    return np.where(peak, 2.0, np.where(night, 0.5, 1.0))


def gas_day_temperature(hourly: pd.Series, profile: str = "flat", step_hours: int = 1) -> pd.Series:
    """hourly: one LDZ's temperature indexed by UTC time (naive, hourly). Returns the weighted mean per gas day."""
    s = hourly.sort_index().astype(float)
    if step_hours > 1:
        s = s.where(s.index.hour % step_hours == 0).interpolate(method="time", limit_area="inside")
    gas_day, local = gas_day_labels(s.index)
    w = hour_weights(local.hour.to_numpy(), profile)
    ok = s.notna().to_numpy()
    frame = pd.DataFrame({"gas_day": gas_day, "wv": np.where(ok, s.to_numpy() * w, 0.0), "w": np.where(ok, w, 0.0),
                          "n": ok.astype(int)})
    g = frame.groupby("gas_day").sum()
    out = g["wv"] / g["w"]
    return out[g["n"] >= MIN_HOURS].rename(hourly.name)
