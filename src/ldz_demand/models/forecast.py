"""
Demand forecasts from the ECMWF ensemble: the final model (models.fit) run on every member.

For each LDZ and member, the member's gas-day weather (ens_ldz_daily: heating-hours temperature, wind,
solar; gas-weighted) goes through the fitted model, giving 50 equally likely demand paths for lead days
0–13. GB is the sum of the LDZs member by member (members are consistent across LDZs).

The effective temperature needs the days before the run. ERA5 runs about five days behind, so the days
between the last ERA5 day and the run are bridged — with the ensemble mean of the most recent earlier run
covering each day, and where no run does, a straight line between the nearest known days. The model
forgets fast (y ≈ 0.4–0.55: a day's weight halves in about a day), so the bridge matters little after the
first days; each run records how many bridged days it used.

    python -m ldz_demand.models.forecast 2026-10-13 2026-10-14   # -> data/results/forecasts/

Demand here is total − DM (the model's target), in GWh/day.
"""

import argparse
import logging
import sys
from datetime import date

import numpy as np
import pandas as pd

from ldz_demand.config import create_config
from ldz_demand.data.datasets import ENS_LDZ_DAILY
from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.data.store import get_store
from ldz_demand.models import demand
from ldz_demand.models import experiment as ex
from ldz_demand.models import fit as final

logger = logging.getLogger(__name__)

LEAD_DAYS = range(0, 14)    # lead day 14 isn't fully covered by the 360-hour run
MIN_COVERAGE_H = 23
HISTORY_DAYS = 60           # warm-up for the effective temperature
VARIABLES = {"t2m_heat": "t2m", "ws10": "ws10", "ssrd": "ssrd"}  # ensemble variable -> model input
OUT = ex.RESULTS / "forecasts"
QUANTILES = (0.1, 0.5, 0.9)


def ensemble(run_date, store=None, ldzs=LDZS) -> pd.DataFrame:
    """One run's member weather: index (ldz, member, gas_day), columns t2m (heating hours), ws10, ssrd."""
    store = store or get_store(create_config())
    membership, weighting = ex.INPUTS[final.MODEL.input]
    run = pd.Timestamp(run_date)
    e = store.read(ENS_LDZ_DAILY, start=run.date(), end=run.date(), membership=membership,
                   variable=list(VARIABLES))
    e = e[(e["weighting"] == weighting) & e["ldz"].isin(ldzs) & e["lead_days"].isin(LEAD_DAYS)
          & (e["coverage_h"] >= MIN_COVERAGE_H)]
    if e.empty:
        raise ValueError(f"No ensemble run for {run.date()} in ens_ldz_daily (build it: python -m "
                         "ldz_demand.data.build.ens_ldz_daily)")
    out = e.pivot_table(index=["ldz", "member", "gas_day"], columns="variable", values="value").rename(columns=VARIABLES)
    missing = [v for v in VARIABLES.values() if v not in out]
    if missing:
        raise ValueError(f"Run {run.date()} has no {missing} (runs archived before 13 Oct 2026 have no solar)")
    return out


def history(run_date, inputs: dict[str, pd.DataFrame], store=None, ldzs=LDZS) -> tuple[dict[str, pd.DataFrame], int]:
    """
    Per LDZ, the HISTORY_DAYS gas days before the run: ERA5 (model_inputs) where it has them, then the
    ensemble mean of earlier runs, then a straight line across any days still missing. Returns the frames
    and how many days were bridged (not ERA5).
    """
    store = store or get_store(create_config())
    run = pd.Timestamp(run_date)
    days = pd.date_range(run - pd.Timedelta(days=HISTORY_DAYS), run - pd.Timedelta(days=1))
    membership, weighting = ex.INPUTS[final.MODEL.input]
    earlier = store.read(ENS_LDZ_DAILY, start=days[0].date(), end=days[-1].date(), membership=membership,
                         variable="t2m_heat")
    earlier = earlier[(earlier["weighting"] == weighting) & (earlier["coverage_h"] >= MIN_COVERAGE_H)]
    # each day from the most recent run covering it (its shortest lead)
    earlier = earlier[earlier["gas_day"] < run].sort_values("lead_days")
    bridge = earlier.groupby(["ldz", "gas_day", "lead_days"])["value"].mean().reset_index()
    bridge = bridge.drop_duplicates(["ldz", "gas_day"]).set_index(["ldz", "gas_day"])["value"]
    out, bridged = {}, 0
    for ldz in ldzs:
        f = inputs[ldz].reindex(days)[["t2m", "ws10", "ssrd"]].copy()
        era5 = f["t2m"].notna()
        if ldz in bridge.index.get_level_values("ldz"):
            b = bridge.xs(ldz, level="ldz").reindex(days)
            f["t2m"] = f["t2m"].fillna(b)
        f["t2m"] = f["t2m"].interpolate(limit_area="inside").ffill()
        f[["ws10", "ssrd"]] = f[["ws10", "ssrd"]].fillna(f[["ws10", "ssrd"]].mean())  # only t2m carries memory
        bridged = max(bridged, int((~era5).sum()))
        out[ldz] = f
    return out, bridged


def forecast(run_date, fits=None, inputs=None, store=None, ldzs=LDZS) -> pd.DataFrame:
    """Per LDZ (and GB), member and gas day: demand (total − DM, GWh/day)."""
    store = store or get_store(create_config())
    fits = fits or final.load()
    inputs = inputs or final.cached_model_inputs(store=store)
    run = pd.Timestamp(run_date)
    ens = ensemble(run, store, ldzs)
    past, bridged = history(run, inputs, store, ldzs)
    rows = []
    for ldz in ldzs:
        for member, m in ens.xs(ldz, level="ldz").groupby(level="member"):
            m = m.droplevel("member")
            frame = pd.concat([past[ldz], m[["t2m", "ws10", "ssrd"]]])
            frame.index = pd.DatetimeIndex(frame.index)
            pred = demand.predict(fits[ldz], frame)[-len(m):]
            rows.append(pd.DataFrame({"ldz": ldz, "member": member, "gas_day": m.index, "demand": pred}))
    out = pd.concat(rows, ignore_index=True)
    gb = out.groupby(["member", "gas_day"], as_index=False)["demand"].sum().assign(ldz="GB")
    out = pd.concat([out, gb], ignore_index=True)
    out["run_date"], out["bridged_days"] = run.normalize(), bridged
    out["lead_days"] = (pd.to_datetime(out["gas_day"]) - run.normalize()).dt.days
    return out


def summary(fc: pd.DataFrame) -> pd.DataFrame:
    """Per LDZ and gas day: mean and the P10 / P50 / P90 across members."""
    g = fc.groupby(["run_date", "ldz", "gas_day", "lead_days"])["demand"]
    out = g.mean().rename("mean").to_frame()
    for q in QUANTILES:
        out[f"p{int(q * 100)}"] = g.quantile(q)
    return out.reset_index().round(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.models.forecast")
    parser.add_argument("runs", nargs="+", help="run dates, YYYY-MM-DD")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = get_store(create_config())
    fits, inputs = final.load(), final.cached_model_inputs(store=store)
    OUT.mkdir(parents=True, exist_ok=True)
    for run in args.runs:
        fc = forecast(run, fits, inputs, store)
        s = summary(fc)
        tag = date.fromisoformat(run).isoformat()
        fc.to_csv(OUT / f"demand_{tag}_members.csv", index=False)
        s.to_csv(OUT / f"demand_{tag}_summary.csv", index=False)
        gb = s[s["ldz"] == "GB"].set_index("gas_day")[["mean", "p10", "p50", "p90"]].round(0)
        logger.info(f"Run {tag} ({fc['bridged_days'].iloc[0]} warm-up days bridged): GB demand, GWh/day\n{gb.to_string()}")
    logger.info(f"Written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
