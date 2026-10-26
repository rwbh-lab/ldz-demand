"""
The scheduled jobs: which steps run, in what order. Any scheduler (cron, launchd, a NAS task, a cloud
scheduler) runs one command per job, usually in the Docker image (deploy/docker/compose.yaml):

    python -m ldz_demand.jobs daily      # ECMWF ensemble: download the latest run, build ens_ldz_daily
    python -m ldz_demand.jobs weekly     # National Gas and ERA5 refresh and builds, then demand forecasts
    python -m ldz_demand.jobs weekly --list

Only the ensemble must be downloaded daily (runs leave the portal after a few days). National Gas keeps
five years and Copernicus all of ERA5, so a weekly refresh loses nothing, and the forecasts are made as
issued (each uses only the ERA5 that existed on its run date), so a weekly batch makes the same forecasts
a daily job would have.

Each step runs in its own process and every step runs even if an earlier one failed (a build still picks
up earlier downloads; the forecasts bridge a missing ERA5 week). The job fails if any step does, so the
scheduler can report it.
"""

import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    label: str
    module: str
    args: tuple[str, ...] = ()

    def command(self) -> list[str]:
        return [sys.executable, "-m", self.module, *self.args]


JOBS: dict[str, tuple[Step, ...]] = {
    "daily": (
        Step("ensemble: download", "ldz_demand.data.ingest.ecmwf_ens", ("refresh",)),
        Step("ensemble: ens_ldz_daily", "ldz_demand.data.build.ens_ldz_daily"),
    ),
    "weekly": (
        Step("national gas: download", "ldz_demand.data.ingest.national_gas", ("refresh",)),
        Step("national gas: ng_ldz_daily", "ldz_demand.data.build.ng_ldz_daily"),
        Step("national gas: ng_offtake_daily", "ldz_demand.data.build.ng_offtake_daily"),
        Step("national gas: ng_forecast_daily", "ldz_demand.data.build.ng_forecast_daily"),
        Step("era5: download", "ldz_demand.data.ingest.era5", ("refresh",)),
        Step("era5: weather_ldz_daily", "ldz_demand.data.build.weather_ldz_daily", ("--recent", "1")),
        Step("forecasts: missing runs", "ldz_demand.models.forecast", ("--missing",)),
    ),
}


def run(job: str, runner=subprocess.run) -> int:
    """Run every step of job; 0 if all succeeded, else the first failing step's exit code."""
    failed = 0
    for step in JOBS[job]:
        logger.info(f"{step.label}: start ({' '.join(step.command()[1:])})")
        start = time.monotonic()
        status = runner(step.command()).returncode
        logger.info(f"{step.label}: finished (exit {status}, {time.monotonic() - start:.0f} s)")
        if status and not failed:
            failed = status
    logger.info(f"{job}: {'failed' if failed else 'done'}")
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.jobs")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--list", action="store_true", help="print the steps without running them")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.list:
        for step in JOBS[args.job]:
            print(f"{step.label:34} python -m {step.module} {' '.join(step.args)}".rstrip())
        return 0
    return run(args.job)


if __name__ == "__main__":
    sys.exit(main())
