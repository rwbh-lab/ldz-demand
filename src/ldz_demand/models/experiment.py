"""
Model experiments (docs/methodology.md §6), scored on held-out gas years.

Experiment "cwv_inputs" (1): which weather input explains LDZ demand best, everything else equal?
- official      the published CWV, straight line, break at 1 Oct 2025 (the benchmark)
- station       ERA5 at the official station, through our CWV form
- sampled_gas   ERA5 over the LDZ (sampled map), weighted by gas use, through our CWV form
- sampled_area  the same, weighted by land area
Target: total - DM (target A, GWh/day). Each gas year from 2021/22 to 2025/26 is held out in turn; the
model is fitted on the others and scored on it. The official CWV changed definition on 1 Oct 2025, so a
held-out year under a definition its training years don't contain (2025/26) can't be scored for it; the
comparison uses the days every input was scored on, and 2025/26 is reported for our inputs separately.

Experiment "seasonal" (3): does a seasonal term help, and does the station need more of it (§5.3)?
For the station and the gas-weighted input: no seasonal term, a slow heating-season temperature, or a
day-of-year shape pooled across LDZs. All with a level / slope break on 1 Oct 2022 (the official CWV
too), so the seasonal term isn't absorbing the post-2022 drop in demand. 2021/22 is then the only year
before the break and can't be held out; the scores cover 2022/23 - 2025/26 (official: to 2024/25).

Experiment "change" (4): how should the model follow changes in behaviour over time? Scored forward:
2023/24, 2024/25 and 2025/26 each predicted from the years before it only (holding out a middle year
can't test this — a level per gas year can't be estimated for the year left out). The gas-weighted
input with the calendar shape, and: fixed; a break on 1 Oct 2022; a level / slope per gas year (the
forecast uses the latest year's); recent years weighted more (half-life 1 or 2 years); and the break /
per-year models with a summer level of their own (demand.summer_weight). The official CWV
(with the 2022 break) as benchmark, to 2024/25.

Experiment "target" (6): target A (total - DM on days that pass the checks) against target B (as A, plus
days a feed was missing from the total, repaired), scored forward. Scores use only days that are real in
both (scores(repaired=False)): a repaired day's "actual" is our repair.

Experiments "variables" (2) and "averaging" (5), forward, on the model chosen after experiment 6 (BEST):
with / without solar, with the day's min / max temperature; and the gas-day temperature rebuilt from
the hourly table — flat, or with the heating hours weighted up — hourly and from 3-hourly steps.

Experiment "final": the model in models.fit (FINAL: BEST with the daily table's heating-hours
temperature, t2m_heat) and the official CWV, forward on target B — the headline scores.

Run:
    python -m ldz_demand.models.experiment cwv_inputs              # all LDZs (a few minutes)
    python -m ldz_demand.models.experiment cwv_inputs --ldz NT WS  # some LDZs
    python -m ldz_demand.models.experiment seasonal
    python -m ldz_demand.models.experiment change
    python -m ldz_demand.models.experiment target
    python -m ldz_demand.models.experiment variables
    python -m ldz_demand.models.experiment averaging
    python -m ldz_demand.models.experiment final
Writes data/results/<experiment>_{predictions,scores,scores_2025_26,params}.csv.
"""

import argparse
import logging
import sys
import time
from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd

from ldz_demand.config import create_config, get_project_root
from ldz_demand.data import ldz_energy as le
from ldz_demand.data.datasets import NG_LDZ_DAILY, NG_OFFTAKE_DAILY, WEATHER_LDZ_DAILY, WEATHER_LDZ_HOURLY
from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.data.store import get_store
from ldz_demand.models import averaging, demand

logger = logging.getLogger(__name__)

INPUTS = {  # name -> weather variant (membership, weighting), or None for the official CWV
    "official": None,
    "station": ("station", "point"),
    "sampled_gas": ("sampled", "gas"),
    "sampled_area": ("sampled", "area"),
}
GAS_YEARS = ("2021/22", "2022/23", "2023/24", "2024/25", "2025/26")
_B, _O = demand.BEHAVIOUR_BREAK, demand.BREAK_DAY


@dataclass(frozen=True)
class Model:
    label: str
    input: str
    seasonal: str = "none"
    breaks: tuple = ()
    per_year: bool = False           # a level / slope per gas year (forward scheme: the latest is used)
    half_life: float | None = None   # recency weighting of training days, years
    summer: bool = False             # a summer level, changing at each break like the rest
    cold: str = "fitted"             # cold-end form (cwv.COLD)
    target: str = "target"           # "target" (A) or "target_repaired" (B)
    extremes: bool = False           # daily min / max temperature in the CWV's temperature
    solar: bool = True               # the solar term (else held at 0)
    temperature: str = "t2m"         # the daily table's temperature: "t2m" (flat mean) or "t2m_heat" (heating hours)


MODELS = {  # experiment -> models
    "cwv_inputs": [Model("official", "official", breaks=(_O,))] + [Model(n, n) for n in INPUTS if n != "official"],
    "seasonal": [Model("official", "official", breaks=(_B, _O))]
                + [Model(f"{n}/{s}", n, s, (_B,)) for n in ("station", "sampled_gas") for s in ("none", "slow", "calendar")],
    "change": [Model("official", "official", breaks=(_B, _O)),
               Model("fixed", "sampled_gas", "calendar"),
               Model("break_2022", "sampled_gas", "calendar", (_B,)),
               Model("per_year", "sampled_gas", "calendar", per_year=True),
               Model("adapting_1y", "sampled_gas", "calendar", half_life=1.0),
               Model("adapting_2y", "sampled_gas", "calendar", half_life=2.0),
               Model("break_2022_summer", "sampled_gas", "calendar", (_B,), summer=True),
               Model("per_year_summer", "sampled_gas", "calendar", per_year=True, summer=True)],
    "target": [m for t, tag in (("target", "A"), ("target_repaired", "B")) for m in (
               Model(f"official/{tag}", "official", breaks=(_B, _O), target=t),
               Model(f"break_2022/{tag}", "sampled_gas", "calendar", (_B,), target=t),
               Model(f"per_year/{tag}", "sampled_gas", "calendar", per_year=True, target=t),
               Model(f"adapting_1y/{tag}", "sampled_gas", "calendar", half_life=1.0, target=t))],
}
BEST = Model("best", "sampled_gas", "calendar", half_life=1.0, target="target_repaired")  # after experiment 6
MODELS["variables"] = [replace(BEST, label="base"), replace(BEST, label="no_solar", solar=False),
                       replace(BEST, label="extremes", extremes=True)]
AVERAGING = [(f"{profile}_{step}h", profile, step) for step in (1, 3) for profile in averaging.PROFILES]
MODELS["averaging"] = [replace(BEST, label="daily_table")] + [replace(BEST, label=label) for label, _, _ in AVERAGING]
FINAL = replace(BEST, label="final", temperature="t2m_heat")  # after experiment 5: the model in models.fit
MODELS["final"] = [Model("official", "official", breaks=(_B, _O), target="target_repaired"), FINAL]
SCHEME = {"cwv_inputs": "held_out", "seasonal": "held_out", "change": "forward", "target": "forward",
          "variables": "forward", "averaging": "forward", "final": "forward"}
FORWARD_FROM = "2023/24"  # forward scheme: the first year predicted (from at least two years before it)


def _folds(scheme: str):
    """(held-out year, training years) per fold."""
    if scheme == "held_out":
        return [(y, tuple(g for g in GAS_YEARS if g != y)) for y in GAS_YEARS]
    return [(y, tuple(g for g in GAS_YEARS if g < y)) for y in GAS_YEARS if y >= FORWARD_FROM]


def _year_starts(years) -> tuple:
    """1 October of each gas year after the first: breaks for a level / slope per gas year."""
    return tuple(pd.Timestamp(f"{y[:4]}-10-01") for y in sorted(years)[1:])
RESULTS = get_project_root() / "data" / "results"
MIN_REGIME_DAYS = 90  # training days needed in each regime a held-out year contains (SE 2022/23 has ~5)
WEATHER_VARIABLES = ("t2m", "t2m_heat", "ws10", "ssrd", "tmin", "tmax")
COLD_SHARE = 0.05  # "coldest days": this share of each LDZ's days, by its gas-weighted temperature


def load(store=None) -> dict[str, pd.DataFrame]:
    """Per LDZ: consecutive gas days with target(s), cwv_official, and the weather variables for every variant used."""
    store = store or get_store(create_config())
    energy = le.energy_frame(store.read(NG_LDZ_DAILY), store.read(NG_OFFTAKE_DAILY))
    weather = store.read(WEATHER_LDZ_DAILY, variable=list(WEATHER_VARIABLES),
                         membership=sorted({v[0] for v in INPUTS.values() if v}))
    weather = weather[weather[["membership", "weighting"]].apply(tuple, axis=1).isin([v for v in INPUTS.values() if v])]
    wide = weather.pivot_table(index=["ldz", "gas_day"], columns=["membership", "weighting", "variable"], values="value")
    frames = {}
    for ldz in LDZS:
        e = energy.xs(ldz, level="ldz")[["target", "target_repaired", "cwv"]].rename(columns={"cwv": "cwv_official"})
        e.index = pd.DatetimeIndex(e.index)
        w = wide.xs(ldz, level="ldz")
        w.index = pd.DatetimeIndex(w.index)
        days = pd.date_range(w.index.min(), w.index.max())  # weather from Sept 2021: spin-up for effective temperature
        frames[ldz] = pd.concat([w.reindex(days), e.reindex(days)], axis=1)
    return frames


def _variant_frame(frame: pd.DataFrame, variant) -> pd.DataFrame:
    out = frame[["target", "target_repaired", "cwv_official"]].copy()
    if variant is not None:
        for var in WEATHER_VARIABLES:
            if (*variant, var) in frame:
                out[var] = frame[(*variant, var)]
    out.columns = [c if isinstance(c, str) else c for c in out.columns]
    return out


def _prepared(frame: pd.DataFrame, name: str, target: str = "target", temperature: str = "t2m"):
    """(data, gas years, usable) for one input: weather inputs keep the full consecutive span. target:
    "target" (A) or "target_repaired" (B, which adds days whose total was repaired); "repaired" marks those."""
    years = le.gas_year(frame.index)
    data = _variant_frame(frame, INPUTS[name])
    data["repaired"] = data["target"].isna() & data["target_repaired"].notna()
    if target == "target_repaired":
        data["target"] = data["target_repaired"]
    if temperature != "t2m" and temperature in data:
        data["t2m"] = data[temperature]
    weather_ok = data[["t2m"]].notna().all(axis=1).to_numpy() if INPUTS[name] else np.ones(len(data), bool)
    usable = data["target"].notna().to_numpy() & weather_ok & np.isin(years, GAS_YEARS)
    if name == "official":
        usable &= data["cwv_official"].notna().to_numpy()
        return data[usable], years[usable], usable[usable]
    data = data.loc[data["t2m"].first_valid_index():data["t2m"].last_valid_index()]
    rows = frame.index.get_indexer(data.index)
    return data, years[rows], usable[rows]


def run(frames: dict[str, pd.DataFrame], ldzs=LDZS, models=None, scheme: str = "held_out") -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Held-out predictions (gas_day, ldz, input, held_out, actual, predicted, cwv) and fitted parameters for
    each model. scheme "held_out": each gas year predicted from all the others; "forward": each year from
    FORWARD_FROM predicted from the years before it. A held-out year is scored only when every regime
    (between breaks) it contains has at least MIN_REGIME_DAYS training days.
    """
    predictions, params = [], []
    for m in models or MODELS["cwv_inputs"]:
        label, name, seasonal = m.label, m.input, m.seasonal
        t0 = time.monotonic()
        prepared = {ldz: _prepared(frames[ldz], name, m.target, m.temperature) for ldz in ldzs}
        for held, train_years in _folds(scheme):
            breaks = tuple(sorted(set(m.breaks) | set(_year_starts(train_years) if m.per_year else ())))
            folds = {}
            for ldz, (data, years_d, usable_d) in prepared.items():
                train, test = usable_d & np.isin(years_d, train_years), usable_d & (years_d == held)
                regime = demand.regimes(data.index, breaks)
                trained = np.bincount(regime[train], minlength=len(breaks) + 1)
                if test.any() and train.sum() >= 200 and (trained[np.unique(regime[test])] >= MIN_REGIME_DAYS).all():
                    folds[ldz] = (data, train, test)
            if not folds:
                continue
            weights = ({ldz: demand.recency_weights(d.index, tr, m.half_life) for ldz, (d, tr, _) in folds.items()}
                       if m.half_life else None)
            if name == "official":
                fits = {ldz: demand.fit_official(d, tr, ldz, breaks) for ldz, (d, tr, _) in folds.items()}
            elif "calendar" in seasonal:  # one shape shared by the LDZs: fitted together
                fits = demand.fit_joint({ldz: (d, tr) for ldz, (d, tr, _) in folds.items()}, seasonal, breaks, weights,
                                        m.summer, m.cold, m.extremes, m.solar)
            else:
                fits = {ldz: demand.fit_weather(d, tr, ldz, seasonal, breaks, weights and weights[ldz], m.summer, m.cold,
                                                m.extremes, m.solar)
                        for ldz, (d, tr, _) in folds.items()}
            for ldz, (data, _, test) in folds.items():
                fit = fits[ldz]
                pred, x = demand.predict(fit, data), demand.cwv_series(fit, data)
                predictions.append(pd.DataFrame({"gas_day": data.index[test], "ldz": ldz, "input": label,
                                                 "held_out": held, "actual": data["target"].to_numpy()[test],
                                                 "repaired": data["repaired"].to_numpy()[test],
                                                 "predicted": pred[test], "cwv": x[test]}))
                row = {"ldz": ldz, "input": label, "held_out": held, "success": fit.success, "n_train": fit.n_train,
                       **dict(zip(fit.columns, fit.coef))}
                if fit.params is not None:
                    row.update({f"p_{k}": v for k, v in asdict(fit.params).items()})
                if fit.shape is not None:
                    row.update({f"shape_{i + 1}": v for i, v in enumerate(fit.shape)})
                params.append(row)
        logger.info(f"{label}: {len(ldzs)} LDZs in {time.monotonic() - t0:.1f} s")
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(params)


def averaged_frames(frames: dict[str, pd.DataFrame], profile: str, step_hours: int, store=None) -> dict[str, pd.DataFrame]:
    """Copies of frames with the gas-weighted temperature rebuilt from the hourly table (experiment 5)."""
    store = store or get_store(create_config())
    hourly = store.read(WEATHER_LDZ_HOURLY, variable="t2m", membership="sampled")
    hourly = hourly[hourly["weighting"] == "gas"]
    out = {}
    for ldz, frame in frames.items():
        h = hourly[hourly["ldz"] == ldz].set_index("time")["value"]
        h.index = pd.DatetimeIndex(h.index)
        f = frame.copy()
        f[("sampled", "gas", "t2m")] = averaging.gas_day_temperature(h, profile, step_hours).reindex(f.index)
        out[ldz] = f
    return out


def run_averaging(frames: dict[str, pd.DataFrame], ldzs=LDZS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Experiment 5: the best model on each gas-day averaging, plus the daily table's own mean."""
    store = get_store(create_config())
    parts = [run(frames, ldzs, [MODELS["averaging"][0]], SCHEME["averaging"])]
    for (label, profile, step), m in zip(AVERAGING, MODELS["averaging"][1:]):
        parts.append(run(averaged_frames(frames, profile, step, store), ldzs, [m], SCHEME["averaging"]))
    return pd.concat([p for p, _ in parts], ignore_index=True), pd.concat([q for _, q in parts], ignore_index=True)


def scores(predictions: pd.DataFrame, frames: dict[str, pd.DataFrame] | None = None, common: bool = True,
           repaired: bool = False) -> pd.DataFrame:
    """
    RMSE / MAPE per LDZ (and GB) and input: all held-out days, winter (Nov-Mar), coldest days. With
    common=True, only days every input was scored on (so inputs are compared on the same days). Days whose
    total was repaired (target B only) are left out unless repaired=True: their "actual" is our repair.
    """
    p = predictions.copy()
    if not repaired and "repaired" in p:
        p = p[~p["repaired"].astype(bool)]
    if common:
        n_inputs = p["input"].nunique()
        p = p[p.groupby(["ldz", "gas_day"])["input"].transform("nunique") == n_inputs]
    p["gas_day"] = pd.to_datetime(p["gas_day"])
    p["error"] = p["predicted"] - p["actual"]
    p["winter"] = p["gas_day"].dt.month.isin([11, 12, 1, 2, 3])
    p["cold"] = False
    if frames is not None:  # coldest days by the gas-weighted LDZ temperature (the same days for every input)
        for ldz, f in frames.items():
            t = f[("sampled", "gas", "t2m")]
            cold_days = set(t[t <= t.quantile(COLD_SHARE)].index)
            m = p["ldz"] == ldz
            p.loc[m, "cold"] = p.loc[m, "gas_day"].isin(cold_days)
    # GB: days where every LDZ has a held-out prediction for that input
    full = p.groupby(["input", "gas_day"])["ldz"].transform("nunique") == len(LDZS)
    gb = p[full].groupby(["input", "gas_day"], as_index=False).agg(
        actual=("actual", "sum"), predicted=("predicted", "sum"), winter=("winter", "first"), cold=("cold", "max"))
    gb["error"], gb["ldz"] = gb["predicted"] - gb["actual"], le.GB
    rows = []
    for (ldz, name), g in pd.concat([p, gb], ignore_index=True).groupby(["ldz", "input"]):
        row = {"ldz": ldz, "input": name, "days": len(g)}
        for label, sel in (("all", slice(None)), ("winter", g["winter"]), ("cold", g["cold"])):
            s = g[sel] if label != "all" else g
            row[f"rmse_{label}"] = float(np.sqrt(np.mean(s["error"] ** 2))) if len(s) else np.nan
            row[f"mape_{label}"] = float(np.mean(np.abs(s["error"]) / s["actual"].abs()) * 100) if len(s) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.models.experiment")
    parser.add_argument("experiment", choices=list(MODELS))
    parser.add_argument("--ldz", nargs="+", default=list(LDZS))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    frames = load()
    models = MODELS[args.experiment]
    if args.experiment == "averaging":
        predictions, params = run_averaging(frames, args.ldz)
    else:
        predictions, params = run(frames, args.ldz, models, SCHEME[args.experiment])
    table = scores(predictions, frames)
    latest = scores(predictions[predictions["held_out"] == "2025/26"], frames).assign(period="2025/26")
    RESULTS.mkdir(parents=True, exist_ok=True)
    for name, df in (("predictions", predictions), ("scores", table), ("scores_2025_26", latest), ("params", params)):
        df.to_csv(RESULTS / f"{args.experiment}_{name}.csv", index=False)
    pd.set_option("display.width", 200)
    summary = table.pivot(index="ldz", columns="input", values="rmse_all").round(2)
    logger.info(f"RMSE (GWh/day), held-out gas years:\n{summary[[m.label for m in models if m.label in summary]].to_string()}")
    logger.info(f"Results -> {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
