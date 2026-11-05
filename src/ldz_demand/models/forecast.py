"""
Demand forecasts from the ECMWF ensemble: the final model (models.fit) run on every member.

For each LDZ and member, the member's gas-day weather (ens_ldz_daily: heating-hours temperature, wind,
solar; gas-weighted) goes through the fitted model, giving 50 equally likely demand paths for lead days
0–13. GB is the sum of the LDZs member by member (members are consistent across LDZs).

The effective temperature needs the days before the run. ERA5 runs about five days behind, so only ERA5
days that would have existed when the run was issued are used (ERA5_LAG_DAYS) — a forecast made later,
in a batch or a catch-up, is the same one made on the day. The days between are bridged with the
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
# actuals(since=...) reads National Gas from this many days earlier: the flags compare each LDZ's non-NTS
# input with its usual level, a median over what is read, so a year keeps every season in it (checked on
# 4 Nov 2026: windows from the full history down to two months gave identical actuals for the live runs)
ACTUALS_MARGIN_DAYS = 365
# How sure each published figure is, as a 10-90% range (lo, hi):
# - provisional (D+1): how far D+1 has moved by the D+6 close-out, for the same LDZ in the same and neighbouring
#   calendar months (10th-90th percentile of d1 / d6 - 1 over the history read), so a D+1 that usually
#   reads high gets a range below it. Needs REVISION_MIN_DAYS such days, else the LDZ's whole year.
# - closed out (D+6): the metering tolerance, METER_TOLERANCE either side. National Gas publishes no
#   per-day uncertainty; the UNC Offtake Arrangements Document (Section D) sets the offtake meters'
#   permitted uncertainty at about +/-1%.
METER_TOLERANCE = 0.01
REVISION_MIN_DAYS = 20


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
    rows += period_mean(ldz_fc, pool, ldzs, rng)
    out = pd.DataFrame(rows)
    out["run_date"], out["run_hour"] = run.normalize(), 0
    out["lead_days"] = (pd.to_datetime(out["gas_day"]) - run.normalize()).dt.days
    out["unit"], out["model"] = "GWh/day", str(pd.read_csv(final.DATA_DIR / final.OUTPUT, comment="#")["fitted_on"].iloc[0])
    return out.round({"value": 2})


PERIOD_PERCENTILES = (10, 50, 90)


def period_mean(ldz_fc: pd.DataFrame, pool: pd.DataFrame, ldzs: list[str], rng) -> list[dict]:
    """
    The mean over every day of the run, as P10 / P50 / P90 per LDZ and GB (statistics "period_p10" ...,
    on the run's last gas day). Not the mean of the daily percentiles: each member's own mean over the days,
    times a model error for a mean of that many days. Model errors run in streaks, so that error comes from
    the record's rolling means over the same number of consecutive days (near the same time of year), not
    from averaging independent daily draws, which would make the range too narrow.
    """
    days = sorted(ldz_fc["gas_day"].unique())
    n = len(days)
    means = ldz_fc.groupby(["member", "ldz"])["demand"].mean().unstack("ldz")[ldzs]      # member x LDZ
    calendar = pool.reindex(pd.date_range(pool.index.min(), pool.index.max()))
    rolling = calendar.rolling(n, min_periods=n).mean().dropna()
    rolling.index = rolling.index - pd.Timedelta(days=n // 2)                              # label by mid-window
    near = _pool_for(pd.Timestamp(days[n // 2]), rolling)[ldzs]
    draws = near.to_numpy()[rng.integers(0, len(near), size=(len(means), DRAWS))]
    samples = means.to_numpy()[:, None, :] * (1 + draws)
    rows = []
    for i, ldz in enumerate([*ldzs, "GB"]):
        s = samples.sum(axis=2) if ldz == "GB" else samples[:, :, i]
        rows += [{"gas_day": days[-1], "ldz": ldz, "statistic": f"period_p{q:02d}", "value": np.percentile(s, q)}
                 for q in PERIOD_PERCENTILES]
    return rows


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


def actuals(store=None, since=None) -> pd.DataFrame:
    """Per LDZ and GB, gas day: the target (total - DM) at D+6 close-out, else the provisional D+1 figure.
    since: the first gas day wanted (default: all); the read starts ACTUALS_MARGIN_DAYS before it."""
    from ldz_demand.data.datasets import NG_LDZ_DAILY, NG_OFFTAKE_DAILY

    store = store or get_store(create_config())
    start = None if since is None else (pd.Timestamp(since) - pd.Timedelta(days=ACTUALS_MARGIN_DAYS)).date()
    raw, offtakes = store.read(NG_LDZ_DAILY, start=start), store.read(NG_OFFTAKE_DAILY, start=start)
    d6 = le.energy_frame(raw, offtakes)["target_repaired"].rename("d6")
    d1 = le.energy_frame(raw, offtakes, closeout="d1")["target_repaired"].rename("d1")
    out = pd.concat([d6, d1], axis=1).reset_index()
    out["actual"] = out["d6"].fillna(out["d1"])
    out["provisional"] = out["d6"].isna() & out["d1"].notna()
    out["gas_day"] = pd.to_datetime(out["gas_day"])
    out = _with_ranges(out)
    if since is not None:
        out = out[out["gas_day"] >= pd.Timestamp(since)]
    return out.dropna(subset=["actual"])[["gas_day", "ldz", "actual", "provisional", "lo", "hi"]]


def revision_ranges(out: pd.DataFrame) -> pd.DataFrame:
    """10th and 90th percentiles of the D+1 -> D+6 revision (d1 / d6 - 1) per LDZ and calendar month, each
    month pooled with its neighbours; LDZ-months with too few days take the LDZ's whole year."""
    both = out[(out["d6"] > 0) & out["d1"].notna()]
    rev = pd.DataFrame({"ldz": both["ldz"], "month": both["gas_day"].dt.month, "r": both["d1"] / both["d6"] - 1})
    rows = []
    for ldz, g in rev.groupby("ldz"):
        for m in range(1, 13):
            near = g[g["month"].isin({(m - 2) % 12 + 1, m, m % 12 + 1})]["r"]
            use = near if len(near) >= REVISION_MIN_DAYS else g["r"]
            if len(use):
                rows.append({"ldz": ldz, "month": m, "r10": use.quantile(0.10), "r90": use.quantile(0.90)})
    return pd.DataFrame(rows, columns=["ldz", "month", "r10", "r90"])


def _with_ranges(out: pd.DataFrame) -> pd.DataFrame:
    """lo, hi: the 10-90% range of each actual (see METER_TOLERANCE above)."""
    out = out.copy()
    out["lo"], out["hi"] = out["actual"] * (1 - METER_TOLERANCE), out["actual"] * (1 + METER_TOLERANCE)
    ranges = revision_ranges(out)
    if ranges.empty or not out["provisional"].any():
        return out
    keyed = out.assign(month=out["gas_day"].dt.month).merge(ranges, on=["ldz", "month"], how="left")
    prov = out["provisional"].to_numpy() & keyed["r10"].notna().to_numpy()
    # the final value is d1 / (1 + r): a high revision (r90) means the final comes in lower
    out.loc[prov, "lo"] = (keyed["d1"] / (1 + keyed["r90"])).to_numpy()[prov]
    out.loc[prov, "hi"] = (keyed["d1"] / (1 + keyed["r10"])).to_numpy()[prov]
    return out


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
