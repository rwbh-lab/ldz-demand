"""
The control: the textbook temperature regression, per LDZ (the challenger experiment, models.experiment).

    demand_t = a + b · max(BASE − T_t, 0) + day of week + bank holiday + Christmas period

T is the flat daily mean temperature (not the heating-hours one) and BASE is the standard UK degree-day
base, fixed rather than fitted: nothing in the control is tuned to the data beyond the straight line.
The gap between it and the CWV model is what the CWV's refinements are worth — the heating hours, the
lag, wind, solar, the cold-end curve and the seasonal shape. Same training days, target and recency
weights as the CWV model (weighted least squares).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ldz_demand.models import calendar

BASE = 15.5  # °C, heating degree-day base


@dataclass
class ControlFit:
    ldz: str
    coef: np.ndarray
    columns: list[str]
    success: bool
    n_train: int


def design(frame: pd.DataFrame, ldz: str) -> tuple[np.ndarray, list[str]]:
    hdd = np.clip(BASE - frame["t2m"].to_numpy(dtype=float), 0, None)
    cal = calendar.features(frame.index, ldz)
    return np.column_stack([np.ones(len(frame)), hdd, cal.to_numpy(dtype=float)]), ["const", "hdd", *cal.columns]


def fit_one(frame: pd.DataFrame, train: np.ndarray, ldz: str, weights: np.ndarray | None = None) -> ControlFit:
    x, columns = design(frame, ldz)
    y = frame["target"].to_numpy(dtype=float)
    sw = np.sqrt(weights[train]) if weights is not None else np.ones(int(train.sum()))
    coef = np.linalg.lstsq(x[train] * sw[:, None], y[train] * sw, rcond=None)[0]
    return ControlFit(ldz, coef, columns, bool(np.isfinite(coef).all()), int(train.sum()))


def fit(data: dict[str, tuple[pd.DataFrame, np.ndarray]], weights=None, model=None) -> dict[str, ControlFit]:
    """Per LDZ, from (frame, training days); weights: per LDZ, per row of the frame (or None)."""
    return {ldz: fit_one(frame, train, ldz, weights[ldz] if weights else None) for ldz, (frame, train) in data.items()}


def predict(fit: ControlFit, frame: pd.DataFrame) -> np.ndarray:
    return design(frame, fit.ldz)[0] @ fit.coef


def params(fit: ControlFit) -> dict:
    return dict(zip(fit.columns, fit.coef))
