"""
ERA5 history for the seasonal normal: hourly temperature and wind (the core variables) for whole past
years, one CDS request per half-year, a few requests in flight at once.

The Copernicus queue, not the download size, is what takes the time, so each request is as large as CDS
allows: six months (a whole year is refused, "cost limits exceeded"), so 62 requests for 31 years rather
than 372. Each download is split
into the usual monthly files (era5_gb_YYYY-MM.nc) under raw_dir/history/era5/<year>/. That is the same
layout as the main archive, so month_files and load_hourly read it with raw_dir/history as their root,
while the daily job's builds, which read raw_dir/era5, never see it.

Run as a script (years inclusive; half-years already on disk are skipped, so it can be rerun):
    python -m ldz_demand.data.ingest.era5_history 1991 2021 --workers 3
"""

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ldz_demand.config import create_config, resolve_path
from ldz_demand.data.ingest.era5 import (DATASET, EXIT_LICENCE, SHORT_NAMES, VARIABLES, _open_download,
                                         licence_error)

logger = logging.getLogger(__name__)

FOLDER = "history"  # under raw_dir; holds era5/<year>/ in the main archive's layout


MONTHS_PER_REQUEST = 6  # the most CDS accepts for 3 variables, hourly, over the GB box
HALVES = (tuple(range(1, 7)), tuple(range(7, 13)))


def year_request(year: int, area, months=range(1, 13)) -> dict:
    """Every hour of the given months. CDS skips the dates that don't exist (31 Feb and so on)."""
    return {
        "product_type": ["reanalysis"],
        "variable": VARIABLES,
        "year": [str(year)],
        "month": [f"{m:02d}" for m in months],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "area": [float(x) for x in area],
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def month_path(root: Path, month: str) -> Path:
    return root / "era5" / month[:4] / f"era5_gb_{month}.nc"


def missing(root: Path, year: int, months=range(1, 13)) -> list[str]:
    return [m for m in (f"{year}-{i:02d}" for i in months) if not month_path(root, m).exists()]


def split_months(ds, root: Path, year: int, months=range(1, 13)) -> list[Path]:
    """Save one download as monthly files; returns the paths written."""
    time = "valid_time" if "valid_time" in ds.coords else "time"
    ds = ds[SHORT_NAMES["core"]]
    saved = []
    for month in missing(root, year, months):
        part = ds.sel({time: month})
        if part.sizes[time] == 0:
            continue
        path = month_path(root, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".nc.part")
        part.to_netcdf(tmp)
        tmp.rename(path)
        saved.append(path)
    return saved


def pull_half(year: int, months, root: Path, area, client=None) -> list[Path]:
    label = f"{year} H{1 if months[0] == 1 else 2}"
    if not missing(root, year, months):
        logger.info(f"{label}: on disk, skipping")
        return []
    if client is None:
        import cdsapi

        client = cdsapi.Client(quiet=True, progress=False)
    raw = root / "era5" / str(year) / f"era5_{year}_{months[0]:02d}.nc.part"
    raw.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"{label}: requesting from CDS (the queue can take minutes to hours)")
    client.retrieve(DATASET, year_request(year, area, months), str(raw))
    try:
        with _open_download(raw) as ds:
            saved = split_months(ds, root, year, months)
    finally:
        raw.unlink(missing_ok=True)
    logger.info(f"{label}: saved {len(saved)} months")
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.ingest.era5_history")
    parser.add_argument("first", type=int)
    parser.add_argument("last", type=int)
    parser.add_argument("--workers", type=int, default=3, help="CDS requests in flight at once")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = create_config()
    area = [x.strip() for x in config["era5"]["area"].split(",")]
    root = resolve_path(config, "storage", "raw_dir") / FOLDER
    chunks = [(y, h) for y in range(args.first, args.last + 1) for h in HALVES if missing(root, y, h)]
    logger.info(f"{len(chunks)} half-years to fetch into {root}")
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(pull_half, y, h, root, area): f"{y} H{1 if h[0] == 1 else 2}" for y, h in chunks}
        for future in as_completed(futures):
            year = futures[future]
            try:
                future.result()
            except Exception as exc:  # one bad year shouldn't stop the others; rerun picks it up
                if error := licence_error(exc):
                    logger.error(f"ACTION NEEDED: {error}")
                    return EXIT_LICENCE
                logger.error(f"{year}: failed: {exc}")
                failed.append(year)
    logger.info(f"done; failed: {sorted(failed) or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
