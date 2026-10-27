"""
Demand forecasts from the ECMWF ensemble: the final model (models.fit) run on every member.

For each LDZ and member, the member's gas-day weather (ens_ldz_daily: heating-hours temperature, wind,
solar; gas-weighted) goes through the fitted model, giving 50 equally likely demand paths for lead days
0–13. GB is the sum of the LDZs member by member (members are consistent across LDZs).

The effective temperature needs the days before the run. ERA5 runs about five days behind, so only ERA5
days that would have existed when the run was issued are used (ERA5_LAG_DAYS) — a forecast made later,
in a weekly batch, is the same one a daily job would have made. The days between are bridged with the
ensemble mean of the most recent earlier run covering each day, and where no run does, a straight line
between the nearest known days. The model
forgets fast (y ≈ 0.4–0.55: a day's weight halves in about a day), so the bridge matters little after the
first days; each run records how many bridged days it used.

Intervals: the members alone give the weather's uncertainty, not the model's — at short leads that is
far too narrow (verified on 13 Oct 2026: the actual fell outside the weather-only P10–P90 in 12 of 13
LDZs). So each member is combined with the model's own out-of-sample errors (models/data/results/
final_residuals.csv, as ratios), drawn from historical days within POOL_DAYS of the same day of the year.
All LDZs take the same historical day, keeping their errors correlated, so GB isn't falsely precise. The
errors are centred within each pool: they widen the interval but don't move it (no bias correction yet).

    python -m ldz_demand.models.forecast 2026-10-13 2026-10-14   # -> demand_forecast_daily (+ CSVs)
    python -m ldz_demand.models.forecast --missing               # every built run not yet forecast

Demand here is total − DM (the model's target), in GWh/day.
"""

import argparse
import logging
import sys
from datetime import date

import numpy as np
import pandas as pd

from ldz_demand.config import create_config
from ldz_demand.data import ldz_energy as le
from ldz_demand.data.datasets import DEMAND_FORECAST_DAILY, ENS_LDZ_DAILY
from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.data.store import get_store
from ldz_demand.models import demand
from ldz_demand.models import experiment as ex
from ldz_demand.models import fit as final
from ldz_demand.models import results

logger = logging.getLogger(__name__)

LEAD_DAYS = range(0, 14)    # lead day 14 isn't fully covered by the 360-hour run
MIN_COVERAGE_H = 23
HISTORY_DAYS = 60           # warm-up for the effective temperature
ERA5_LAG_DAYS = 6           # a run issued on day R could use ERA5 gas days up to R - ERA5_LAG_DAYS
VARIABLES = {"t2m_heat": "t2m", "ws10": "ws10", "ssrd": "ssrd"}  # ensemble variable -> model input
OUT = ex.RESULTS / "forecasts"
POOL_DAYS = 30              # model errors from historical days within this many days of the day of year
DRAWS = 40                  # model-error draws per member
PERCENTILES = (5, 10, 25, 50, 75, 90, 95)


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
        f.loc[f.index > run - pd.Timedelta(days=ERA5_LAG_DAYS), "t2m"] = np.nan  # not yet available at issue
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


def error_pool(residuals: pd.DataFrame | None = None) -> pd.DataFrame:
    """The model's out-of-sample errors as ratios: index gas day (all LDZs present), one column per LDZ."""
    r = results.load("final_residuals") if residuals is None else residuals
    return r.pivot(index="gas_day", columns="ldz", values="ratio").dropna()


def _pool_for(day: pd.Timestamp, pool: pd.DataFrame) -> pd.DataFrame:
    doy = pool.index.day_of_year.to_numpy()
    gap = np.abs(doy - day.day_of_year)
    near = pool[np.minimum(gap, 365 - gap) <= POOL_DAYS]
    return near - near.mean()  # centred: spread only


def statistics(fc: pd.DataFrame, pool: pd.DataFrame | None = None, seed: int | None = None) -> pd.DataFrame:
    """
    Per LDZ (and GB) and gas day: the mean and P05 – P95 with model error, and the weather-only P10 / P90
    (across members alone). Long rows (statistic, value), as demand_forecast_daily.
    """
    pool = error_pool() if pool is None else pool
    run = pd.Timestamp(fc["run_date"].iloc[0])
    rng = np.random.default_rng(seed if seed is not None else int(run.strftime("%Y%m%d")))
    ldz_fc = fc[fc["ldz"] != "GB"]
    ldzs = [c for c in pool.columns if c in set(ldz_fc["ldz"])]
    rows = []
    for day, g in ldz_fc.groupby("gas_day"):
        paths = g.pivot(index="member", columns="ldz", values="demand")[ldzs]       # member x LDZ
        near = _pool_for(pd.Timestamp(day), pool)[ldzs]
        draws = near.to_numpy()[rng.integers(0, len(near), size=(len(paths), DRAWS))]  # member x draw x LDZ
        samples = paths.to_numpy()[:, None, :] * (1 + draws)
        for i, ldz in enumerate([*ldzs, "GB"]):
            s = samples.sum(axis=2) if ldz == "GB" else samples[:, :, i]
            w = paths.sum(axis=1) if ldz == "GB" else paths[ldz]
            stats = {"mean": s.mean(), **{f"p{q:02d}": np.percentile(s, q) for q in PERCENTILES},
                     "weather_p10": np.percentile(w, 10), "weather_p90": np.percentile(w, 90)}
            rows += [{"gas_day": day, "ldz": ldz, "statistic": k, "value": v} for k, v in stats.items()]
    out = pd.DataFrame(rows)
    out["run_date"], out["run_hour"] = run.normalize(), 0
    out["lead_days"] = (pd.to_datetime(out["gas_day"]) - run.normalize()).dt.days
    out["unit"], out["model"] = "GWh/day", str(pd.read_csv(final.DATA_DIR / final.OUTPUT, comment="#")["fitted_on"].iloc[0])
    return out.round({"value": 2})


def summary(stats: pd.DataFrame) -> pd.DataFrame:
    """statistics() as one row per LDZ and gas day."""
    return stats.pivot_table(index=["run_date", "ldz", "gas_day", "lead_days"], columns="statistic",
                             values="value").reset_index()


def load_runs(store=None) -> pd.DataFrame:
    """Every stored forecast (statistics() rows): demand_forecast_daily, or the CSVs in OUT if the table isn't there."""
    store = store or get_store(create_config())
    try:
        stored = store.read(DEMAND_FORECAST_DAILY)
    except Exception:
        stored = pd.DataFrame()
    if not stored.empty:
        return stored
    files = sorted(OUT.glob("demand_*_summary.csv"))
    if not files:
        return pd.DataFrame()
    wide = pd.concat([pd.read_csv(f, parse_dates=["run_date", "gas_day"]) for f in files], ignore_index=True)
    return wide.melt(id_vars=["run_date", "ldz", "gas_day", "lead_days"], var_name="statistic", value_name="value")


def actuals(store=None) -> pd.DataFrame:
    """Per LDZ and GB, gas day: the target (total - DM) at D+6 close-out, else the provisional D+1 figure."""
    from ldz_demand.data.datasets import NG_LDZ_DAILY, NG_OFFTAKE_DAILY

    store = store or get_store(create_config())
    raw, offtakes = store.read(NG_LDZ_DAILY), store.read(NG_OFFTAKE_DAILY)
    d6 = le.energy_frame(raw, offtakes)["target_repaired"].rename("d6")
    d1 = le.energy_frame(raw, offtakes, closeout="d1")["target_repaired"].rename("d1")
    out = pd.concat([d6, d1], axis=1).reset_index()
    out["actual"] = out["d6"].fillna(out["d1"])
    out["provisional"] = out["d6"].isna() & out["d1"].notna()
    out["gas_day"] = pd.to_datetime(out["gas_day"])
    return out.dropna(subset=["actual"])[["gas_day", "ldz", "actual", "provisional"]]


def missing_runs(store=None) -> list[str]:
    """Built ensemble runs with the model's inputs (t2m_heat and solar) but no stored forecast, oldest first."""
    store = store or get_store(create_config())
    membership, weighting = ex.INPUTS[final.MODEL.input]
    built = store.read(ENS_LDZ_DAILY, ldz="NT", member=1, lead_days=0, membership=membership, variable=["t2m_heat", "ssrd"])
    built = built[built["weighting"] == weighting]
    usable = built.groupby("run_date")["variable"].nunique()
    runs = {pd.Timestamp(d).date() for d in usable[usable == 2].index}
    try:
        stored = store.read(DEMAND_FORECAST_DAILY, ldz="GB", statistic="p50", lead_days=0)
        done = {pd.Timestamp(d).date() for d in stored["run_date"].unique()}
    except Exception:  # no table yet
        done = set()
    return [d.isoformat() for d in sorted(runs - done)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.models.forecast")
    parser.add_argument("runs", nargs="*", help="run dates, YYYY-MM-DD")
    parser.add_argument("--missing", action="store_true", help="every built run not yet forecast")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = get_store(create_config())
    runs = list(args.runs) + (missing_runs(store) if args.missing else [])
    if not runs:
        logger.info("No runs to forecast" + (" (every built run already has one)" if args.missing else ""))
        return 0
    fits, inputs, pool = final.load(), final.cached_model_inputs(store=store), error_pool()
    OUT.mkdir(parents=True, exist_ok=True)
    for run in runs:
        fc = forecast(run, fits, inputs, store)
        stats = statistics(fc, pool)
        tag = date.fromisoformat(run).isoformat()
        fc.to_csv(OUT / f"demand_{tag}_members.csv", index=False)
        summary(stats).to_csv(OUT / f"demand_{tag}_summary.csv", index=False)
        try:
            n = store.write(DEMAND_FORECAST_DAILY, stats, on_conflict="replace")
        except Exception as exc:  # e.g. the table doesn't exist yet in MySQL
            n = 0
            logger.warning(f"Not written to {DEMAND_FORECAST_DAILY.name} ({exc.__class__.__name__}: {str(exc)[:120]}); "
                           "in MySQL mode apply the migration first: python -m ldz_demand.db migrate")
        gb = summary(stats).query("ldz == 'GB'").set_index("gas_day")[["p10", "p50", "p90", "weather_p10", "weather_p90"]]
        logger.info(f"Run {tag} ({fc['bridged_days'].iloc[0]} warm-up days bridged; {n} rows to "
                    f"{DEMAND_FORECAST_DAILY.name}): GB demand, GWh/day\n{gb.round(0).to_string()}")
    logger.info(f"Member paths and summaries also in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
