"""
Raw inputs → a feature table, for the models that aren't CWV (models.control, models.ebm).

The same information the CWV model gets, without its engineering: the gas-day temperature (heating
hours, as in the final model), the two days before it (the CWV's effective temperature carries the
same memory), wind, solar, the time of year and the calendar flags from models.calendar (so every model
sees the same weekdays and holidays). The frame is the one demand.predict takes — consecutive gas days,
columns t2m, ws10, ssrd — so the forecast's warm-up history works unchanged; the first two rows have no
lagged temperature.

Time of year is days since 1 October (the gas year), one column rather than a sine / cosine pair: an
additive model draws it as a single curve, and the wrap-around falls at the end of September, outside
the heating season.
"""

import numpy as np
import pandas as pd

from ldz_demand.models import calendar

FEATURES = ("t", "t_lag1", "t_lag2", "ws10", "ssrd", "season_day", "weekday", "bank_holiday", "christmas")
CATEGORICAL = ("weekday",)
MONOTONE = {"t": -1, "t_lag1": -1, "t_lag2": -1, "ws10": 1, "ssrd": -1}  # demand falls with warmth and sun, rises with wind


def season_day(gas_days) -> np.ndarray:
    """Days since the 1 October that starts each gas day's gas year (0-365)."""
    days = pd.DatetimeIndex(gas_days)
    start_year = np.where(days.month >= 10, days.year, days.year - 1)
    starts = pd.to_datetime([f"{y}-10-01" for y in start_year])
    return (days - starts).days.to_numpy()


def features(frame: pd.DataFrame, ldz: str) -> pd.DataFrame:
    """One row per row of frame (consecutive gas days), the columns in FEATURES."""
    days = pd.DatetimeIndex(frame.index)
    if len(days) > 1 and ((days[1:] - days[:-1]) != pd.Timedelta(days=1)).any():
        raise ValueError("features: the frame's gas days must be consecutive (the lags are by row)")
    t = frame["t2m"].astype(float)
    cal = calendar.features(days, ldz)
    sr = frame["ssrd"].astype(float)
    out = pd.DataFrame({
        "t": t.to_numpy(),
        "t_lag1": t.shift(1).to_numpy(),
        "t_lag2": t.shift(2).to_numpy(),
        "ws10": frame["ws10"].to_numpy(dtype=float),
        "ssrd": sr.fillna(sr.mean()).to_numpy(),  # a few edge days without solar: the mean, as demand._inputs
        "season_day": season_day(days),
        "weekday": days.day_of_week.to_numpy(),
        "bank_holiday": cal["bank_holiday"].to_numpy(),
        "christmas": cal["christmas"].to_numpy(),
    }, index=days)
    return out[list(FEATURES)]
