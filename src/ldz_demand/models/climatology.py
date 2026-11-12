"""
Climatology: demand from the time of year and the weekday alone, no weather (the challenger experiment's floor).

Per LDZ, the (recency-weighted) mean demand of the training days within WINDOW days of each day of the
gas year (models.features.season_day, wrapping round at the year end), plus a weekday offset: the mean
of what is left on each weekday. What weather forecasts are worth is the gap between it and the rest.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ldz_demand.models.features import season_day

WINDOW = 7    # days either side
YEAR_DAYS = 366


@dataclass
class ClimatologyFit:
    ldz: str
    seasonal: np.ndarray  # mean demand per season day, 0..365
    weekday: np.ndarray   # offset per weekday, Monday first
    success: bool
    n_train: int


def _seasonal(sd: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    gap = np.abs(np.arange(YEAR_DAYS)[:, None] - sd[None, :])
    near = np.minimum(gap, YEAR_DAYS - gap) <= WINDOW
    return (near * w) @ y / (near @ w)


def fit_one(frame: pd.DataFrame, train: np.ndarray, ldz: str, weights: np.ndarray | None = None) -> ClimatologyFit:
    sd, wd = season_day(frame.index)[train], frame.index.day_of_week.to_numpy()[train]
    y = frame["target"].to_numpy(dtype=float)[train]
    w = weights[train] if weights is not None else np.ones(len(y))
    seasonal = _seasonal(sd, y, w)
    r = y - seasonal[sd]
    weekday = np.array([np.average(r[wd == d], weights=w[wd == d]) for d in range(7)])
    return ClimatologyFit(ldz, seasonal, weekday, bool(np.isfinite(seasonal).all()), int(train.sum()))


def fit(data: dict[str, tuple[pd.DataFrame, np.ndarray]], weights=None, model=None) -> dict[str, ClimatologyFit]:
    """Per LDZ, from (frame, training days); weights: per LDZ, per row of the frame (or None)."""
    return {ldz: fit_one(frame, train, ldz, weights[ldz] if weights else None) for ldz, (frame, train) in data.items()}


def predict(fit: ClimatologyFit, frame: pd.DataFrame) -> np.ndarray:
    return fit.seasonal[season_day(frame.index)] + fit.weekday[frame.index.day_of_week.to_numpy()]


def params(fit: ClimatologyFit) -> dict:
    return {f"weekday_{d}": v for d, v in zip(("mon", "tue", "wed", "thu", "fri", "sat", "sun"), fit.weekday)}
