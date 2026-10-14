"""
LDZ demand as a straight line in a composite weather variable, plus calendar effects.

    demand_t = a + b · CWV_t + day of week + bank holiday + Christmas period
               [+ a change in a and b after each break]
               [+ c · w_t, w_t the summer weight: 0 on heating days, 1 above the summer cut-off; also
                  changing after each break — summer demand (hot water, cooking) needn't move with heating]

Two kinds of fit, per LDZ:
- "weather": CWV built from our weather (ldz_demand.models.cwv); its parameters and the linear terms are
  fitted together. With the "calendar" seasonal term the LDZs are fitted jointly (fit_joint), as they
  share one day-of-year shape;
- "official": the published CWV as given, linear terms only.

Breaks: the intercept and slope may change on given days — BEHAVIOUR_BREAK (demand after the 2022 price
shock) and, for the official CWV, BREAK_DAY (when its parameters and seasonal normal changed). A break's
terms can only be estimated from training days after it, so held-out years are scored only when every
regime they contain appears in training (`regimes`).

Both use a robust loss (soft L1), so a few odd days — data errors, one-off events — don't pull the fit.
The weather series must be consecutive gas days (effective temperatures carry over from day to day);
`train` selects the days the fit uses.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.signal import lfilter
from scipy.sparse import lil_matrix

from ldz_demand.models import calendar, cwv

BREAK_DAY = pd.Timestamp("2025-10-01")        # official CWV redefined (2024 review)
BEHAVIOUR_BREAK = pd.Timestamp("2022-10-01")  # demand after the 2022 price shock
HARMONICS = 2                                 # sine / cosine pairs in the calendar shape
YEAR = 365.25
SHAPE_BOUND = 3.0                             # on each shape coefficient (the first cosine's is fixed at 1)


def effective_temperature(t: np.ndarray, y: float) -> np.ndarray:
    """E_t = y · E_t−1 + (1 − y) · T_t from E_0 = T_0 (vectorised)."""
    return lfilter([1 - y], [1, -y], t, zi=[y * t[0]])[0]


def harmonics(gas_days, n: int | None = None) -> np.ndarray:
    """(days, 2n): cos, sin of 1..n cycles a year, by day of year (n: HARMONICS)."""
    n = n or HARMONICS
    w = 2 * np.pi * pd.DatetimeIndex(gas_days).dayofyear.to_numpy() / YEAR
    return np.column_stack([f(k * w) for k in range(1, n + 1) for f in (np.cos, np.sin)])


def composite_weather(t, w, sr, p: cwv.CWVParams, s: np.ndarray | None = None, g: np.ndarray | None = None) -> np.ndarray:
    """CW, before the piecewise transform. s: a seasonal temperature mixed in with weight 1 - I1; g: a
    calendar shape added as Sc · g."""
    e = effective_temperature(t, p.y)
    base = e if s is None else p.I1 * e + (1 - p.I1) * s
    if g is not None:
        base = base + p.Sc * g
    return base - p.I2 * np.maximum(0.0, w - p.W0) * np.maximum(0.0, p.T0 - t) + p.S0 * sr


def summer_weight(cw: np.ndarray, p: cwv.CWVParams) -> np.ndarray:
    """0 for CW <= V1 (heating), rising linearly to 1 at V2 (the summer cut-off) and above."""
    return np.clip((cw - p.V1) / p.dV, 0.0, 1.0)


def composite(t, w, sr, p: cwv.CWVParams, s: np.ndarray | None = None, g: np.ndarray | None = None) -> np.ndarray:
    """The CWV (see composite_weather for s and g)."""
    return transform(composite_weather(t, w, sr, p, s, g), p)


def transform(cw: np.ndarray, p: cwv.CWVParams) -> np.ndarray:
    """The piecewise CWV transform: summer cut-off, transition, cold-weather upturn."""
    v1, v2 = p.V1, p.V2
    out = np.where(cw >= v2, v1 + p.q * (v2 - v1), cw)
    out = np.where((cw > v1) & (cw < v2), v1 + p.q * (cw - v1), out)
    return np.where(cw < p.V0, cw + p.I3 * (cw - p.V0), out)


def regimes(gas_days, breaks=()) -> np.ndarray:
    """Per day, how many breaks it is on or after (0 = before all of them)."""
    days = pd.DatetimeIndex(gas_days)
    return sum(((days >= b).astype(int) for b in breaks), np.zeros(len(days), int))


@dataclass
class Fit:
    kind: str                       # "weather" or "official"
    ldz: str
    coef: np.ndarray                # linear terms, in the order of `columns`
    columns: list[str]
    params: cwv.CWVParams | None    # weather fits only
    success: bool
    n_train: int
    seasonal: str = "none"
    breaks: tuple = ()
    shape: np.ndarray | None = None  # calendar shape coefficients after the first (shared by the LDZs fitted together)
    summer: bool = False             # summer level term (weather fits)
    cold: str = "fitted"             # cold-end form (cwv.COLD)
    extremes: bool = False           # daily min / max temperature in T (weights m_min, m_max)
    solar: bool = True               # solar term S0 (else held at 0)


def _design(x: np.ndarray, cal: pd.DataFrame, breaks=(), summer: np.ndarray | None = None) -> tuple[np.ndarray, list[str]]:
    cols = [np.ones(len(x)), x]
    names = ["intercept", "cwv"]
    if summer is not None:
        cols.append(summer)
        names.append("summer")
    for b in breaks:
        post = (cal.index >= b).astype(float)
        cols += [post, post * x]
        names += [f"intercept_after_{b:%Y-%m}", f"cwv_after_{b:%Y-%m}"]
        if summer is not None:
            cols.append(post * summer)
            names.append(f"summer_after_{b:%Y-%m}")
    cols += [cal[c].to_numpy() for c in cal.columns]
    return np.column_stack(cols), names + list(cal.columns)


def _robust_scale(r: np.ndarray) -> float:
    return max(1.4826 * float(np.median(np.abs(r - np.median(r)))), 1e-6)


def _inputs(frame: pd.DataFrame):
    """(t, w, sr, tmin, tmax): tmin / tmax None if the frame has no extremes."""
    t, w, sr = (frame[c].to_numpy(dtype=float) for c in ("t2m", "ws10", "ssrd"))
    sr = np.nan_to_num(sr, nan=float(np.nanmean(sr)))  # a few edge days without solar: use the mean
    ext = [frame[c].to_numpy(dtype=float) if c in frame else None for c in ("tmin", "tmax")]
    return t, w, sr, *ext


def temperature(t, tmin, tmax, p: cwv.CWVParams) -> np.ndarray:
    """The temperature the CWV uses: the gas-day mean, moved towards the day's min / max by m_min / m_max."""
    if (p.m_min == 0 and p.m_max == 0) or tmin is None:
        return t
    return t + p.m_min * (np.where(np.isnan(tmin), t, tmin) - t) + p.m_max * (np.where(np.isnan(tmax), t, tmax) - t)


def calendar_shape(gas_days, shape, h=None) -> np.ndarray:
    """g: the first cosine (coefficient 1) plus the fitted coefficients on the other harmonics."""
    h = harmonics(gas_days) if h is None else h
    return h[:, 0] + h[:, 1:] @ shape


def _seasonal(t, gas_days, p: cwv.CWVParams, seasonal: str, shape=None, h=None):
    """(s, g) for composite."""
    s = effective_temperature(t, p.ys) if "slow" in seasonal else None
    g = calendar_shape(gas_days, shape, h) if "calendar" in seasonal else None
    return s, g


def fit_weather(frame: pd.DataFrame, train: np.ndarray, ldz: str, seasonal: str = "none", breaks=(),
                weights: np.ndarray | None = None, summer: bool = False, cold: str = "fitted",
                extremes: bool = False, solar: bool = True) -> Fit:
    """frame: consecutive gas days with t2m, ws10, ssrd (tmin, tmax), target. Fits on rows where train is True."""
    return fit_joint({ldz: (frame, train)}, seasonal, breaks, None if weights is None else {ldz: weights}, summer,
                     cold, extremes, solar)[ldz]


def recency_weights(gas_days, train: np.ndarray, half_life: float) -> np.ndarray:
    """Per day, 0.5 ** (age / half_life), age in years before the last training day."""
    days = pd.DatetimeIndex(gas_days)
    age = (days[train].max() - days).days.to_numpy() / YEAR
    return 0.5 ** (np.clip(age, 0, None) / half_life)


def fit_joint(data: dict[str, tuple[pd.DataFrame, np.ndarray]], seasonal: str = "none", breaks=(),
              weights: dict[str, np.ndarray] | None = None, summer: bool = False,
              cold: str = "fitted", extremes: bool = False, solar: bool = True) -> dict[str, Fit]:
    """
    Fit several LDZs in one problem: each has its own CWV parameters and linear terms; with the
    "calendar" seasonal term they share the day-of-year shape. Each LDZ's residuals are divided by its
    robust scale, so the large LDZs don't decide the shape. weights: per LDZ, per day (all rows of the
    frame), multiplying each day's share of the loss.
    """
    names = cwv.free_names(seasonal, cold, extremes, solar)
    k, n_shape = len(names), 2 * HARMONICS - 1 if "calendar" in seasonal else 0
    blocks = []
    for ldz, (frame, train) in data.items():
        t, w, sr, tmin, tmax = _inputs(frame)
        lo, hi = cwv.bounds(ldz, names, cold)
        base = cwv.fixed_values(ldz, cold, solar)
        blocks.append(dict(ldz=ldz, t=t, w=w, sr=sr, tmin=tmin, tmax=tmax, y=frame["target"].to_numpy(dtype=float), train=train,
                           cal=calendar.features(frame.index, ldz), days=frame.index, lo=lo, hi=hi,
                           p0=np.clip(base.vector(names), lo, hi), base=base,
                           sw=np.sqrt(weights[ldz][train]) if weights else 1.0,
                           h=harmonics(frame.index) if n_shape else None))

    def x_of(b, p_vec, shape):
        p = cwv.CWVParams.from_vector(p_vec, names, b["base"])
        t = temperature(b["t"], b["tmin"], b["tmax"], p)
        s, g = _seasonal(t, b["days"], p, seasonal, shape, b["h"])
        cw = composite_weather(t, b["w"], b["sr"], p, s, g)
        return _design(transform(cw, p), b["cal"], breaks, summer_weight(cw, p) if summer else None)[0]

    theta0, lo, hi, slices, start = [np.zeros(n_shape)], [np.full(n_shape, -SHAPE_BOUND)], [np.full(n_shape, SHAPE_BOUND)], [], n_shape
    for b in blocks:
        x0 = x_of(b, b["p0"], np.zeros(n_shape))
        beta0 = np.linalg.lstsq(x0[b["train"]], b["y"][b["train"]], rcond=None)[0]
        b["scale"] = _robust_scale(x0[b["train"]] @ beta0 - b["y"][b["train"]])
        nb = len(beta0)
        theta0 += [b["p0"], beta0]
        lo += [b["lo"], np.full(nb, -np.inf)]
        hi += [b["hi"], np.full(nb, np.inf)]
        slices.append((slice(start, start + k), slice(start + k, start + k + nb)))
        start += k + nb
    theta0, lo, hi = np.concatenate(theta0), np.concatenate(lo), np.concatenate(hi)

    def residuals(theta):
        shape = theta[:n_shape]
        return np.concatenate([b["sw"] * (x_of(b, theta[ps], shape)[b["train"]] @ theta[bs] - b["y"][b["train"]]) / b["scale"]
                               for b, (ps, bs) in zip(blocks, slices)])

    rows = [int(b["train"].sum()) for b in blocks]
    sparsity = lil_matrix((sum(rows), len(theta0)), dtype=int)  # each LDZ's rows: its own terms + the shape
    r0 = 0
    for n, (ps, bs) in zip(rows, slices):
        sparsity[r0:r0 + n, :n_shape] = 1
        sparsity[r0:r0 + n, ps.start:bs.stop] = 1
        r0 += n
    res = least_squares(residuals, theta0, bounds=(lo, hi), loss="soft_l1", f_scale=1.0, x_scale="jac",
                        jac_sparsity=sparsity if len(blocks) > 1 else None, max_nfev=3000)
    columns = _design(np.zeros(1), blocks[0]["cal"].iloc[:1], breaks, np.zeros(1) if summer else None)[1]
    shape = res.x[:n_shape] if n_shape else None
    return {b["ldz"]: Fit("weather", b["ldz"], res.x[bs], columns, cwv.CWVParams.from_vector(res.x[ps], names, b["base"]),
                          bool(res.success), int(b["train"].sum()), seasonal, tuple(breaks), shape, summer, cold,
                          extremes, solar)
            for b, (ps, bs) in zip(blocks, slices)}


def fit_official(frame: pd.DataFrame, train: np.ndarray, ldz: str, breaks=(BREAK_DAY,)) -> Fit:
    """frame: gas days with cwv_official, target. Linear terms only, with the given breaks."""
    x, names = _design(frame["cwv_official"].to_numpy(dtype=float), calendar.features(frame.index, ldz), breaks)
    y = frame["target"].to_numpy(dtype=float)
    beta0 = np.linalg.lstsq(x[train], y[train], rcond=None)[0]
    scale = _robust_scale(x[train] @ beta0 - y[train])
    res = least_squares(lambda b: x[train] @ b - y[train], beta0, loss="soft_l1", f_scale=scale, x_scale="jac")
    return Fit("official", ldz, res.x, names, None, bool(res.success), int(train.sum()), breaks=tuple(breaks))


def _cw(fit: Fit, frame: pd.DataFrame) -> np.ndarray:
    t, w, sr, tmin, tmax = _inputs(frame)
    t = temperature(t, tmin, tmax, fit.params)
    s, g = _seasonal(t, frame.index, fit.params, fit.seasonal, fit.shape)
    return composite_weather(t, w, sr, fit.params, s, g)


def cwv_series(fit: Fit, frame: pd.DataFrame) -> np.ndarray:
    """The fitted CWV for every row (weather fits), or the official CWV (official fits)."""
    if fit.kind == "official":
        return frame["cwv_official"].to_numpy(dtype=float)
    return transform(_cw(fit, frame), fit.params)


def predict(fit: Fit, frame: pd.DataFrame) -> np.ndarray:
    """Predicted target for every row of frame (same layout as for the fit)."""
    summer = summer_weight(_cw(fit, frame), fit.params) if fit.summer else None
    x, _ = _design(cwv_series(fit, frame), calendar.features(frame.index, fit.ldz), fit.breaks, summer)
    return x @ fit.coef
