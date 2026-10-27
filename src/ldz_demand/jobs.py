"""
The scheduled job: which steps run, in what order. Any scheduler (cron, launchd, a NAS task, a cloud
scheduler) runs one command a day, usually in the Docker image (deploy/docker/compose.yaml):

    python -m ldz_demand.jobs daily      # refresh every source, build the tables, forecast the new runs
    python -m ldz_demand.jobs daily --list

A job is a list of stages; a stage's branches run side by side, each branch's steps in order:

    1. ensemble: download -> build             | National Gas: download -> builds; ERA5: download -> build
    2. forecasts for every new run (needs both: the run, and the ERA5 that existed on its run date)

The ensemble is the heavy branch (~10 GB of download, then decoding); ERA5 is mostly waiting in the
Copernicus queue, so running them together costs little and the job ends with the slower of the two.
Start it after the 00z run is complete (~09:30 UTC; 10:45 UK is safe all year). Only the ensemble must be
downloaded every day (runs leave the portal after a few days); the others are refreshed daily so the
forecasts and their verification are current. "weekly" is the same job under its earlier name.

Each step runs in its own process and every step runs even if an earlier one failed (a build still picks
up earlier downloads; the forecasts bridge missing ERA5 days). The job fails if any step does, so the
scheduler can report it.
"""

import argparse
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    label: str
    module: str
    args: tuple[str, ...] = ()

    def command(self) -> list[str]:
        return [sys.executable, "-m", self.module, *self.args]


Branch = tuple[Step, ...]  # steps run in order
Stage = tuple[Branch, ...]  # branches run side by side

ENSEMBLE: Branch = (
    Step("ensemble: download", "ldz_demand.data.ingest.ecmwf_ens", ("refresh",)),
    Step("ensemble: ens_ldz_daily", "ldz_demand.data.build.ens_ldz_daily"),
)
GAS_AND_WEATHER: Branch = (
    Step("national gas: download", "ldz_demand.data.ingest.national_gas", ("refresh",)),
    Step("national gas: ng_ldz_daily", "ldz_demand.data.build.ng_ldz_daily"),
    Step("national gas: ng_offtake_daily", "ldz_demand.data.build.ng_offtake_daily"),
    Step("national gas: ng_forecast_daily", "ldz_demand.data.build.ng_forecast_daily"),
    Step("era5: download", "ldz_demand.data.ingest.era5", ("refresh",)),
    Step("era5: weather_ldz_daily", "ldz_demand.data.build.weather_ldz_daily", ("--recent", "1")),
)
FORECASTS: Branch = (
    Step("forecasts: missing runs", "ldz_demand.models.forecast", ("--missing",)),
)

DAILY: tuple[Stage, ...] = ((ENSEMBLE, GAS_AND_WEATHER), (FORECASTS,))
JOBS: dict[str, tuple[Stage, ...]] = {"daily": DAILY, "weekly": DAILY}


def steps(job: str) -> list[Step]:
    """Every step of job, in listed order."""
    return [step for stage in JOBS[job] for branch in stage for step in branch]


def run_branch(branch: Branch, runner=subprocess.run) -> list[int]:
    """Run a branch's steps in order (all of them, whatever fails); their exit codes."""
    statuses = []
    for step in branch:
        logger.info(f"{step.label}: start ({' '.join(step.command()[1:])})")
        start = time.monotonic()
        status = runner(step.command()).returncode
        logger.info(f"{step.label}: finished (exit {status}, {time.monotonic() - start:.0f} s)")
        statuses.append(status)
    return statuses


def run(job: str, runner=subprocess.run) -> int:
    """Run every stage of job; 0 if all steps succeeded, else the first failing step's exit code (listed order)."""
    statuses = []
    for stage in JOBS[job]:
        with ThreadPoolExecutor(max_workers=len(stage)) as pool:
            for branch_statuses in pool.map(lambda branch: run_branch(branch, runner), stage):
                statuses += branch_statuses
    failed = next((status for status in statuses if status), 0)
    logger.info(f"{job}: {'failed' if failed else 'done'}")
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.jobs")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--list", action="store_true", help="print the steps without running them")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.list:
        for number, stage in enumerate(JOBS[args.job], 1):
            print(f"stage {number}" + (" (branches side by side)" if len(stage) > 1 else ""))
            for branch in stage:
                for step in branch:
                    print(f"  {step.label:34} python -m {step.module} {' '.join(step.args)}".rstrip())
                if len(stage) > 1 and branch is not stage[-1]:
                    print("  " + "-" * 34)
        return 0
    return run(args.job)


if __name__ == "__main__":
    sys.exit(main())
