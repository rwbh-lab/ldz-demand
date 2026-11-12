"""
The challenger: an Explainable Boosting Machine on the raw inputs, pooled across the LDZs.

An EBM is a generalised additive model fitted by boosting (the `interpret` package): demand is a sum of
one curve per input plus a few pairwise interactions, each of which can be drawn. Same inputs as the
CWV model, before its engineering (models.features: the heating-hours temperature, the two days before,
wind, solar, the day of the gas year, the calendar flags), plus the LDZ as a category; same training
days, target B and recency weights (models.experiment, family "ebm").

Pooled: one model for the 13 LDZs, the target divided by each LDZ's (weighted) mean demand on its
training days, so the large LDZs don't decide the shared curves (as fit_joint scales each LDZ's
residuals). Monotone: demand may only fall as the temperatures and solar rise and only rise with wind
(features.MONOTONE). The EBM's own monotone_constraints stop the boosting almost at once (interpret
0.7.8: a 5 % error on a noise-free curve, against 0.1 % without), so the model is fitted freely and each
of those curves then made monotone (EBM.monotonize, isotonic regression on the term). That shapes the
one-input curves only: a pairwise interaction with them can still bend the total a little.

The EBM tests the method only: the same inputs as the CWV model, no new features. (Given the two
features the error tree found, as bridge days and a forced weekday × temperature pair, it gained less
than the CWV model did: GB RMSE 49.5 → 48.3 GWh/day, against 43.7 → 41.8; tested 12 Nov 2026, not kept.)

The time of year goes in as 30-day blocks of the gas year, not single days: with three or four training
years a day-by-day curve learns those winters' weather as "season" (GB RMSE on the tuning fold 62
GWh/day by day, 60 in 15-day blocks, 55 in 30- or 60-day blocks; 61 with sine / cosine pairs instead).
Settings chosen on the 2024/25 forward fold (trained on 2021/22-2023/24): 10 pairwise interactions
(0: 67, 25: 68); the learning rate and leaf size made no difference.
"""

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ldz_demand.models.features import CATEGORICAL, FEATURES, MONOTONE, features

COLUMNS = (*FEATURES, "ldz")
NOMINAL = (*CATEGORICAL, "ldz", "bank_holiday", "christmas")
SETTINGS = dict(interactions=10, outer_bags=8, learning_rate=0.015, random_state=0)
SEASON_BLOCK = 30  # days of the gas year per step of the season term


@dataclass
class EBMFit:
    ldz: str
    model: object   # the pooled ExplainableBoostingRegressor (shared by the LDZs fitted together)
    scale: float    # the LDZ's mean target on its training days: predictions are model × scale
    success: bool
    n_train: int


def table(frame: pd.DataFrame, ldz: str) -> pd.DataFrame:
    f = features(frame, ldz)
    return f.assign(ldz=ldz, season_day=f["season_day"] // SEASON_BLOCK)[list(COLUMNS)]


def regressor(**settings):
    from interpret.glassbox import ExplainableBoostingRegressor

    return ExplainableBoostingRegressor(
        feature_names=list(COLUMNS), feature_types=["nominal" if c in NOMINAL else "continuous" for c in COLUMNS],
        **{**SETTINGS, **settings})


def fit(data: dict[str, tuple[pd.DataFrame, np.ndarray]], weights=None, model=None, **settings) -> dict[str, EBMFit]:
    """One EBM for the LDZs in data, from (frame, training days); weights: per LDZ, per row of the frame (or None)."""
    xs, ys, ws, scales = [], [], [], {}
    for ldz, (frame, train) in data.items():
        w = weights[ldz][train] if weights else np.ones(int(train.sum()))
        y = frame["target"].to_numpy(dtype=float)[train]
        scales[ldz] = float(np.average(y, weights=w))
        xs.append(table(frame, ldz)[train])
        ys.append(y / scales[ldz])
        ws.append(w)
    x, y, w = pd.concat(xs, ignore_index=True), np.concatenate(ys), np.concatenate(ws)
    with warnings.catch_warnings():  # the first rows' lagged temperatures are missing: interpret warns about its graphs
        warnings.filterwarnings("ignore", message="Missing values detected")
        ebm = regressor(**settings).fit(x, y, sample_weight=w)
    for c, sign in MONOTONE.items():
        ebm.monotonize(c, increasing=sign > 0)
    return {ldz: EBMFit(ldz, ebm, scales[ldz], True, len(y)) for ldz, y in zip(data, ys)}


def predict(fit: EBMFit, frame: pd.DataFrame) -> np.ndarray:
    return fit.model.predict(table(frame, fit.ldz)) * fit.scale


def params(fit: EBMFit) -> dict:
    return {"scale": fit.scale}


def terms(fit: EBMFit) -> pd.DataFrame:
    """Each term's share of the model (mean absolute contribution, the `interpret` importance), largest first."""
    m = fit.model
    return pd.DataFrame({"term": m.term_names_, "importance": m.term_importances()}).sort_values(
        "importance", ascending=False, ignore_index=True)
