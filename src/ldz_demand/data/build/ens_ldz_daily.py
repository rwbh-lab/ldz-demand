"""
Builds ens_ldz_daily: ECMWF ensemble gas-day forecast weather per LDZ, member by member.

For each archived run (raw_dir/ecmwf_ens): the forecast steps of every member -> LDZ means with the
same cell weights as weather_ldz_daily (only the [ldz_weather] detail_variants) -> gas-day means.
The steps are 3-hourly to day 6 and 6-hourly after, so a gas day has 8 or 4 samples (one day has
both); method "flat" weights each sample by the time it stands for, and coverage_h records the hours
of the gas day the steps cover (lead day 14 ends a few hours after the last step). Lead days 0
(the run's own gas day, already a few hours old when the run is published) to 14.

The gridded runs stay archived, so the table can be rebuilt with another averaging method or
variant at any time. Rows are written with replace.

Run as a script:
    python -m ldz_demand.data.build.ens_ldz_daily                     # runs not built yet
    python -m ldz_demand.data.build.ens_ldz_daily --since 2026-10-10  # every run from that date
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ldz_demand.config import create_config, resolve_path
from ldz_demand.data.build.gas_day import gas_day_time_mean
from ldz_demand.data.build.weather_ldz_daily import KEY, VARIABLES, weight_arrays
from ldz_demand.data.datasets import ENS_LDZ_DAILY
from ldz_demand.data.ingest.ecmwf_ens import archived_runs, load_run
from ldz_demand.data.store import Store, get_store

logger = logging.getLogger(__name__)

LEAD_DAYS = range(0, 15)


def ens_ldz_daily(run_data: xr.Dataset, weights: pd.DataFrame, run: datetime, method: str = "flat") -> pd.DataFrame:
    """Gas-day LDZ means per member from one run (dims time, number, latitude, longitude) as long rows."""
    arrays = weight_arrays(weights, run_data["latitude"].values, run_data["longitude"].values)
    times = pd.DatetimeIndex(run_data["time"].values)
    members = run_data["number"].values
    run_date = pd.Timestamp(run).normalize()
    gas_days = pd.DatetimeIndex([run_date + pd.Timedelta(days=k) for k in LEAD_DAYS])
    frames = []
    for variable, unit in VARIABLES.items():
        keys, w = arrays[variable]
        field = run_data[variable].transpose("number", "time", "latitude", "longitude").values
        series = np.einsum("ntij,kij->nkt", field, w)                  # member x variant-LDZ x step
        means, covered = gas_day_time_mean(series, times, gas_days, method)  # member x variant-LDZ x gas day
        n, k, d = np.meshgrid(np.arange(len(members)), np.arange(len(keys)), np.arange(len(gas_days)), indexing="ij")
        frame = keys.iloc[k.ravel()].reset_index(drop=True)
        frame["member"] = members[n.ravel()]
        frame["gas_day"] = gas_days[d.ravel()]
        frame["coverage_h"] = covered[d.ravel()].round(3)
        frame["value"] = means.ravel()
        frames.append(frame.assign(variable=variable, unit=unit))
    out = pd.concat(frames, ignore_index=True)
    out = out[(out["coverage_h"] > 0) & out["value"].notna()]
    out["lead_days"] = (out["gas_day"] - run_date).dt.days
    return out.assign(run_date=run_date, run_hour=pd.Timestamp(run).hour, method=method)


class EnsLdzDailyBuilder:
    """
    Parameters
    ----------
    store : Store
        Destination for ENS_LDZ_DAILY.
    raw_dir : Path
        Raw archive root (ensemble runs under raw_dir/ecmwf_ens).
    weights : DataFrame, optional
        Cell weights, already narrowed to the variants wanted; defaults to the committed weights
        narrowed to the [ldz_weather] detail_variants.
    method : str
        Gas-day averaging method (see ldz_demand.data.build.gas_day.gas_day_time_mean).
    """

    def __init__(self, store: Store, raw_dir: Path, weights: pd.DataFrame | None = None, method: str = "flat") -> None:
        self.store = store
        self.raw_dir = Path(raw_dir)
        if weights is None:
            from ldz_demand.geo import grid_weights

            weights = grid_weights.select(grid_weights.load(), grid_weights.detail_variants())
        self.weights = weights
        self.method = method

    def build(self, since: date | None = None) -> int:
        """Build archived runs from `since` (default: those after the last run already built)."""
        runs = archived_runs(self.raw_dir)
        if since is None:
            last = self.store.last_date(ENS_LDZ_DAILY, method=self.method)
            todo = [r for r in runs if last is None or r.date() > last]
        else:
            todo = [r for r in runs if r.date() >= since]
        if not todo:
            logger.info("No new ensemble runs to build")
            return 0
        written = 0
        for run in todo:
            rows = ens_ldz_daily(load_run(self.raw_dir, run), self.weights, run, self.method)
            n = self.store.write(ENS_LDZ_DAILY, rows, on_conflict="replace")
            logger.info(f"{run:%Y-%m-%d %Hz}: {rows['member'].nunique()} members, lead days "
                        f"{rows['lead_days'].min()}-{rows['lead_days'].max()}, {n} rows")
            written += n
        return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.build.ens_ldz_daily")
    parser.add_argument("--since", help="build every run from this date, YYYY-MM-DD (default: runs not built yet)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = create_config()
    builder = EnsLdzDailyBuilder(get_store(config), resolve_path(config, "storage", "raw_dir"))
    builder.build(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
