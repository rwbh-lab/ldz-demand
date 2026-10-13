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

Run:
    python -m ldz_demand.models.experiment cwv_inputs              # all LDZs (a few minutes)
    python -m ldz_demand.models.experiment cwv_inputs --ldz NT WS  # some LDZs
    python -m ldz_demand.models.experiment seasonal
Writes data/results/<experiment>_{predictions,scores,scores_2025_26,params}.csv.
"""

import argparse
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from ldz_demand.config import create_config, get_project_root
from ldz_demand.data import ldz_energy as le
from ldz_demand.data.datasets import NG_LDZ_DAILY, NG_OFFTAKE_DAILY, WEATHER_LDZ_DAILY
from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.data.store import get_store
from ldz_demand.models import demand

logger = logging.getLogger(__name__)

INPUTS = {  # name -> weather variant (membership, weighting), or None for the official CWV
    "official": None,
    "station": ("station", "point"),
    "sampled_gas": ("sampled", "gas"),
    "sampled_area": ("sampled", "area"),
}
GAS_YEARS = ("2021/22", "2022/23", "2023/24", "2024/25", "2025/26")
_B, _O = demand.BEHAVIOUR_BREAK, demand.BREAK_DAY
MODELS = {  # experiment -> models: (label, input, seasonal term, breaks)
    "cwv_inputs": [("official", "official", "none", (_O,))] + [(n, n, "none", ()) for n in INPUTS if n != "official"],
    "seasonal": [("official", "official", "none", (_B, _O))]
                + [(f"{n}/{s}", n, s, (_B,)) for n in ("station", "sampled_gas") for s in ("none", "slow", "calendar")],
}
RESULTS = get_project_root() / "data" / "results"
COLD_SHARE = 0.05  # "coldest days": this share of each LDZ's days, by its gas-weighted temperature


def load(store=None) -> dict[str, pd.DataFrame]:
    """Per LDZ: consecutive gas days with target, cwv_official, and t2m / ws10 / ssrd for every variant used."""
    store = store or get_store(create_config())
    energy = le.energy_frame(store.read(NG_LDZ_DAILY), store.read(NG_OFFTAKE_DAILY))
    weather = store.read(WEATHER_LDZ_DAILY, variable=["t2m", "ws10", "ssrd"],
                         membership=sorted({v[0] for v in INPUTS.values() if v}))
    weather = weather[weather[["membership", "weighting"]].apply(tuple, axis=1).isin([v for v in INPUTS.values() if v])]
    wide = weather.pivot_table(index=["ldz", "gas_day"], columns=["membership", "weighting", "variable"], values="value")
    frames = {}
    for ldz in LDZS:
        e = energy.xs(ldz, level="ldz")[["target", "cwv"]].rename(columns={"cwv": "cwv_official"})
        e.index = pd.DatetimeIndex(e.index)
        w = wide.xs(ldz, level="ldz")
        w.index = pd.DatetimeIndex(w.index)
        days = pd.date_range(w.index.min(), w.index.max())  # weather from Sept 2021: spin-up for effective temperature
        frames[ldz] = pd.concat([w.reindex(days), e.reindex(days)], axis=1)
    return frames


def _variant_frame(frame: pd.DataFrame, variant) -> pd.DataFrame:
    out = frame[["target", "cwv_official"]].copy()
    if variant is not None:
        for var in ("t2m", "ws10", "ssrd"):
            out[var] = frame[(*variant, var)]
    out.columns = [c if isinstance(c, str) else c for c in out.columns]
    return out


def _prepared(frame: pd.DataFrame, name: str):
    """(data, gas years, usable) for one input: weather inputs keep the full consecutive span."""
    years = le.gas_year(frame.index)
    data = _variant_frame(frame, INPUTS[name])
    weather_ok = data[["t2m"]].notna().all(axis=1).to_numpy() if INPUTS[name] else np.ones(len(data), bool)
    usable = data["target"].notna().to_numpy() & weather_ok & np.isin(years, GAS_YEARS)
    if name == "official":
        usable &= data["cwv_official"].notna().to_numpy()
        return data[usable], years[usable], usable[usable]
    data = data.loc[data["t2m"].first_valid_index():data["t2m"].last_valid_index()]
    rows = frame.index.get_indexer(data.index)
    return data, years[rows], usable[rows]


def run(frames: dict[str, pd.DataFrame], ldzs=LDZS, models=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Held-out predictions (gas_day, ldz, input, held_out, actual, predicted, cwv) and fitted parameters for
    each model (label, input, seasonal term, breaks). A held-out year is scored only when every regime
    (between breaks) it contains also appears in its training years.
    """
    predictions, params = [], []
    for label, name, seasonal, breaks in models or MODELS["cwv_inputs"]:
        t0 = time.monotonic()
        prepared = {ldz: _prepared(frames[ldz], name) for ldz in ldzs}
        for held in GAS_YEARS:
            folds = {}
            for ldz, (data, years_d, usable_d) in prepared.items():
                train, test = usable_d & (years_d != held), usable_d & (years_d == held)
                regime = demand.regimes(data.index, breaks)
                if test.any() and train.sum() >= 200 and set(regime[test]) <= set(regime[train]):
                    folds[ldz] = (data, train, test)
            if not folds:
                continue
            if name == "official":
                fits = {ldz: demand.fit_official(d, tr, ldz, breaks) for ldz, (d, tr, _) in folds.items()}
            elif seasonal == "calendar":  # one shape shared by the LDZs: fitted together
                fits = demand.fit_joint({ldz: (d, tr) for ldz, (d, tr, _) in folds.items()}, seasonal, breaks)
            else:
                fits = {ldz: demand.fit_weather(d, tr, ldz, seasonal, breaks) for ldz, (d, tr, _) in folds.items()}
            for ldz, (data, _, test) in folds.items():
                fit = fits[ldz]
                pred, x = demand.predict(fit, data), demand.cwv_series(fit, data)
                predictions.append(pd.DataFrame({"gas_day": data.index[test], "ldz": ldz, "input": label,
                                                 "held_out": held, "actual": data["target"].to_numpy()[test],
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


def scores(predictions: pd.DataFrame, frames: dict[str, pd.DataFrame] | None = None, common: bool = True) -> pd.DataFrame:
    """
    RMSE / MAPE per LDZ (and GB) and input: all held-out days, winter (Nov-Mar), coldest days. With
    common=True, only days every input was scored on (so inputs are compared on the same days).
    """
    p = predictions.copy()
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
    predictions, params = run(frames, args.ldz, models)
    table = scores(predictions, frames)
    latest = scores(predictions[predictions["held_out"] == "2025/26"], frames).assign(period="2025/26")
    RESULTS.mkdir(parents=True, exist_ok=True)
    for name, df in (("predictions", predictions), ("scores", table), ("scores_2025_26", latest), ("params", params)):
        df.to_csv(RESULTS / f"{args.experiment}_{name}.csv", index=False)
    pd.set_option("display.width", 200)
    summary = table.pivot(index="ldz", columns="input", values="rmse_all").round(2)
    logger.info(f"RMSE (GWh/day), held-out gas years:\n{summary[[m[0] for m in models if m[0] in summary]].to_string()}")
    logger.info(f"Results -> {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
