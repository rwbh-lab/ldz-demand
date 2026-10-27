"""
Quick start: the final model on a sample ensemble run, with no downloads, training, keys or database.

    python -m ldz_demand.quickstart                  # forecast the sample run -> data/quickstart/
    LDZ_DEMAND_CONFIG=config/quickstart.ini marimo run dashboard/live_forecasts.py   # then look at it

The sample (data/sample/, committed) is the ECMWF ensemble run of 5 January 2025, three days before
the coldest spell of that winter (8-11 January), already built to LDZ gas-day weather, plus the 60 days
of ERA5 before it that the effective temperature needs and National Gas's actuals for the days it
covers. The fitted model ships with the package (models/data/final_fit.csv). Each run copies the sample
into data/quickstart/ (git-ignored), forecasts it exactly as the daily job would (models.forecast) and
writes the result there as a CSV-store table that the Live forecasts page can read.

The run is as issued: the last ERA5_LAG_DAYS days before it are bridged, as in a live forecast. Live,
the bridge is the ensemble mean of the previous days' runs; the sample has no earlier runs, so it is a
straight carry-forward of the last ERA5 day (the run reports how many days were bridged).

    python -m ldz_demand.quickstart --make-sample    # maintainer: rebuild data/sample/ from the full store
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

import pandas as pd

from ldz_demand.config import get_project_root
from ldz_demand.data.datasets import DEMAND_FORECAST_DAILY, ENS_LDZ_DAILY, NG_LDZ_DAILY, NG_OFFTAKE_DAILY
from ldz_demand.data.store.csv_cache import CsvCacheStore
from ldz_demand.models import experiment as ex
from ldz_demand.models import fit as final
from ldz_demand.models import forecast as fcm

logger = logging.getLogger(__name__)

RUN = pd.Timestamp("2025-01-05")
SAMPLE = get_project_root() / "data" / "sample"
WORK = get_project_root() / "data" / "quickstart"
INPUTS = "model_inputs.csv"
ACTUAL_DAYS = (-7, 20)  # National Gas days kept around the run, relative to it


def sample_inputs() -> dict[str, pd.DataFrame]:
    """The sample's model inputs per LDZ, as models.fit.model_inputs() returns them."""
    df = pd.read_csv(SAMPLE / INPUTS, parse_dates=["gas_day"])
    return {ldz: g.drop(columns="ldz").set_index("gas_day").rename_axis(None).asfreq("D") for ldz, g in df.groupby("ldz")}


def run(work: Path = WORK) -> pd.DataFrame:
    """Forecast the sample run into work; returns the GB summary with the actuals alongside."""
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(SAMPLE, work)
    store = CsvCacheStore(work)
    fc = fcm.forecast(RUN, final.load(), sample_inputs(), store)
    stats = fcm.statistics(fc, fcm.error_pool())
    store.write(DEMAND_FORECAST_DAILY, stats, on_conflict="replace")
    tag = RUN.date().isoformat()
    fc.to_csv(work / f"demand_{tag}_members.csv", index=False)
    summary = fcm.summary(stats)
    summary.to_csv(work / f"demand_{tag}_summary.csv", index=False)
    logger.info(f"{fc['bridged_days'].iloc[0]} warm-up days bridged")

    actual = fcm.actuals(store).query("ldz == 'GB'").set_index("gas_day")["actual"]
    gb = summary.query("ldz == 'GB'").set_index("gas_day")[["lead_days", "p10", "p50", "p90"]]
    gb["actual"] = actual.reindex(gb.index)
    gb["in P10-P90"] = gb["actual"].between(gb["p10"], gb["p90"]).where(gb["actual"].notna())
    return gb


def make_sample(store=None) -> None:
    """Rebuild data/sample/ from the full store (CSV or MySQL, per config): the run, its inputs, the actuals."""
    from ldz_demand.config import create_config
    from ldz_demand.data.store import get_store

    store = store or get_store(create_config())
    membership, weighting = ex.INPUTS[final.MODEL.input]
    SAMPLE.mkdir(parents=True, exist_ok=True)
    sample = CsvCacheStore(SAMPLE)

    ens = store.read(ENS_LDZ_DAILY, start=RUN.date(), end=RUN.date(), membership=membership,
                     variable=list(fcm.VARIABLES))
    ens = ens[(ens["weighting"] == weighting) & ens["lead_days"].isin(fcm.LEAD_DAYS)]
    if ens.empty:
        raise ValueError(f"No ensemble run for {RUN.date()} in the store: pull it with --source aws and build it")
    sample.write(ENS_LDZ_DAILY, ens, on_conflict="replace")

    inputs = final.cached_model_inputs(store=store)
    first = RUN - pd.Timedelta(days=fcm.HISTORY_DAYS)
    frames = {ldz: f.loc[first:RUN - pd.Timedelta(days=1)] for ldz, f in inputs.items()}
    pd.concat(frames, names=["ldz", "gas_day"]).reset_index().to_csv(SAMPLE / INPUTS, index=False)

    start, end = (RUN + pd.Timedelta(days=d) for d in ACTUAL_DAYS)
    for dataset in (NG_LDZ_DAILY, NG_OFFTAKE_DAILY):
        sample.write(dataset, store.read(dataset, start=start.date(), end=end.date()), on_conflict="replace")
    logger.info(f"Sample written to {SAMPLE}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.quickstart")
    parser.add_argument("--make-sample", action="store_true", help="rebuild data/sample/ from the full store")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.make_sample:
        make_sample()
        return 0
    gb = run()
    with pd.option_context("display.width", 120):
        print(f"\nGB demand forecast from the ECMWF ensemble run of {RUN:%d %b %Y}, GWh/day "
              "(total less directly connected sites)\n")
        print(gb.round(0).to_string())
    print(f"\nOutputs in {WORK.relative_to(get_project_root())}/. To see them on the Live forecasts page:\n"
          "  LDZ_DEMAND_CONFIG=config/quickstart.ini marimo run dashboard/live_forecasts.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
