"""
ERA5 ingestor (Copernicus Climate Data Store) — download and archive, plus reading the archive.

Hourly 2m temperature and 10m wind (u, v) over a GB box, one NetCDF file per month, archived under
raw_dir/era5/<year>/. A second group, "extra", holds surface solar radiation (ssrd) and total
precipitation (tp) in their own monthly files (era5x_...), so they can be added to an existing
archive without downloading temperature and wind again; load_hourly merges them when present. Requires a free CDS account, ~/.cdsapirc with your API token, and the ERA5
licence accepted on the dataset page.

Final vs preliminary data: ERA5 is published with ~5 days' latency as preliminary "ERA5T", which
is replaced by final ERA5 about 2-3 months later (values can change slightly). Months older than
FINAL_AFTER_DAYS are downloaded once to era5_gb_YYYY-MM.nc and never fetched again. More recent
months are downloaded to a new era5t_gb_YYYY-MM_pulled_<UTC time>.nc on each pull, unless an earlier
pull already reaches the month's last day (then the next download is the final file); load_hourly uses the
final file when present, else the latest preliminary one. So a daily refresh asks CDS for the current
month (and the previous one for its last days), not every preliminary month again.

Gas-day aggregation and LDZ weighting happen in ldz_demand.data.build, not here.

Run as a script:
    python -m ldz_demand.data.ingest.era5 refresh
    python -m ldz_demand.data.ingest.era5 pull 2021-09 2026-09
"""

import argparse
import logging
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ldz_demand.config import create_config, resolve_path

logger = logging.getLogger(__name__)

DATASET = "reanalysis-era5-single-levels"
VARIABLES = ["2m_temperature", "10m_u_component_of_wind", "10m_v_component_of_wind"]
EXTRA_VARIABLES = ["surface_solar_radiation_downwards", "total_precipitation"]
GROUPS = {"core": (VARIABLES, "era5"), "extra": (EXTRA_VARIABLES, "era5x")}  # group -> (variables, file prefix)
FINAL_AFTER_DAYS = 90  # months ending longer ago than this are treated as final ERA5
LATENCY_DAYS = 6  # ERA5T is available ~5 days behind real time

FINAL_NAME = re.compile(r"era5_gb_(\d{4}-\d{2})\.nc")
PRELIM_NAME = re.compile(r"era5t_gb_(\d{4}-\d{2})_pulled_(\w+)\.nc")


def _names(group: str) -> tuple[re.Pattern, re.Pattern]:
    """(final, preliminary) filename patterns for a group."""
    prefix = GROUPS[group][1]
    return (re.compile(rf"{prefix}_gb_(\d{{4}}-\d{{2}})\.nc"),
            re.compile(rf"{prefix}t_gb_(\d{{4}}-\d{{2}})_pulled_(\w+)\.nc"))


class ERA5Ingestor:
    """
    Downloads monthly ERA5 files for a GB box.

    Parameters
    ----------
    raw_dir : Path
        Raw archive root; files go to raw_dir/era5/<year>/.
    area : sequence of float
        north, west, south, east in degrees.
    client : cdsapi.Client, optional
        Injectable for testing. Created on first download otherwise (reads ~/.cdsapirc).
    group : str
        "core" (temperature, wind) or "extra" (solar radiation, precipitation); see GROUPS.
    """

    def __init__(self, raw_dir: Path, area, client=None, group: str = "core") -> None:
        if group not in GROUPS:
            raise ValueError(f"group must be one of {list(GROUPS)}, got {group!r}")
        self.raw_dir = Path(raw_dir) / "era5"
        self.area = [float(x) for x in area]
        self._client = client
        self.group = group
        self.variables, self.prefix = GROUPS[group]

    @property
    def client(self):
        if self._client is None:
            import cdsapi

            self._client = cdsapi.Client()
        return self._client

    def pull(self, first: str, last: str, today: date | None = None) -> list[Path]:
        """Download months first..last (YYYY-MM, inclusive). Final months already on disk are skipped."""
        today = today or date.today()
        downloaded = []
        for month in _months(first, last):
            if is_final(month, today):
                path = self.final_path(month)
                if path.exists():
                    logger.info(f"{month}: final file exists, skipping")
                    continue
            elif self.complete_pull(month):
                logger.info(f"{month}: preliminary file covers the whole month, skipping until final")
                continue
            else:
                pulled = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                path = self.raw_dir / month[:4] / f"{self.prefix}t_gb_{month}_pulled_{pulled}.nc"
            self.download(month, path, today)
            downloaded.append(path)
        return downloaded

    def refresh(self, start: str, today: date | None = None) -> list[Path]:
        """Download everything from start to the latest available month."""
        today = today or date.today()
        latest = (today - timedelta(days=LATENCY_DAYS)).strftime("%Y-%m")
        return self.pull(start, latest, today)

    def complete_pull(self, month: str) -> bool:
        """Whether the latest preliminary pull of month already reaches its last day."""
        _, prelim_name = _names(self.group)
        pulls = sorted((m.group(2), p) for p in (self.raw_dir / month[:4]).glob("*.nc")
                       if (m := prelim_name.fullmatch(p.name)) and m.group(1) == month)
        if not pulls:
            return False
        with xr.open_dataset(pulls[-1][1]) as ds:
            time = ds["valid_time"] if "valid_time" in ds.variables else ds["time"]
            last = pd.Timestamp(time.values.max())
        return last.date() >= _month_end(month)

    def final_path(self, month: str) -> Path:
        return self.raw_dir / month[:4] / f"{self.prefix}_gb_{month}.nc"

    def download(self, month: str, path: Path, today: date) -> None:
        year, mon = month.split("-")
        last_day = min(_month_end(month), today - timedelta(days=LATENCY_DAYS)).day
        request = {
            "product_type": ["reanalysis"],
            "variable": self.variables,
            "year": [year],
            "month": [mon],
            "day": [f"{d:02d}" for d in range(1, last_day + 1)],
            "time": [f"{h:02d}:00" for h in range(24)],
            "area": self.area,
            "data_format": "netcdf",
            "download_format": "unarchived",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".nc.part")
        logger.info(f"{month}: requesting {last_day} days of {self.group} variables from CDS "
                    "(queued requests can take minutes)")
        self.client.retrieve(DATASET, request, str(tmp))
        tmp.rename(path)
        logger.info(f"{month}: saved {path}")


def is_final(month: str, today: date) -> bool:
    return _month_end(month) < today - timedelta(days=FINAL_AFTER_DAYS)


def month_files(raw_dir: Path, group: str = "core") -> dict[str, Path]:
    """month -> file to use: the final file if present, else the latest preliminary pull."""
    final_name, prelim_name = _names(group)
    chosen: dict[str, tuple[int, str, Path]] = {}
    for path in sorted((Path(raw_dir) / "era5").rglob("*.nc")):
        if m := final_name.fullmatch(path.name):
            rank = (1, "")
        elif m := prelim_name.fullmatch(path.name):
            rank = (0, m.group(2))
        else:
            continue
        month = m.group(1)
        if month not in chosen or rank > chosen[month][:2]:
            chosen[month] = (*rank, path)
    return {month: entry[2] for month, entry in sorted(chosen.items())}


def load_hourly(raw_dir: Path, first: str | None = None, last: str | None = None, extra: bool = True) -> xr.Dataset:
    """
    Hourly t2m (degC), u10, v10 and wind speed ws10 (m/s) on (time, latitude, longitude), UTC; plus,
    for months whose extra files are archived (and extra=True), ssrd (mean W m-2) and tp (mm) over
    the hour ending at each time (missing for months without them).
    """
    def pick(group):
        return [p for m, p in month_files(raw_dir, group).items()
                if (first is None or m >= first) and (last is None or m <= last)]

    files = pick("core")
    if not files:
        raise FileNotFoundError(f"No ERA5 files under {Path(raw_dir) / 'era5'} for {first}..{last}")
    ds = _concat([_standardise(xr.open_dataset(p)) for p in files])
    extra_files = pick("extra") if extra else []
    if extra_files:
        ds = xr.merge([ds, _concat([_standardise_extra(xr.open_dataset(p)) for p in extra_files])], join="left")
    return ds


def _concat(parts: list[xr.Dataset]) -> xr.Dataset:
    ds = xr.concat(parts, dim="time").sortby("time")
    return ds.isel(time=~ds.get_index("time").duplicated())


def _standardise_extra(ds: xr.Dataset) -> xr.Dataset:
    """Hourly accumulations as delivered (J m-2, m) -> mean W m-2 and mm over the hour."""
    if "valid_time" in ds.dims or "valid_time" in ds.coords:
        ds = ds.rename({"valid_time": "time"})
    ds = ds.drop_vars([v for v in ("number", "expver") if v in ds.variables])
    out = xr.Dataset({"ssrd": ds["ssrd"] / 3600.0, "tp": (ds["tp"] * 1000.0).clip(min=0)})
    out["ssrd"].attrs["units"] = "W m-2"
    out["tp"].attrs["units"] = "mm"
    return out


def _standardise(ds: xr.Dataset) -> xr.Dataset:
    """Normalise names/units across CDS file versions."""
    if "valid_time" in ds.dims or "valid_time" in ds.coords:
        ds = ds.rename({"valid_time": "time"})
    ds = ds.drop_vars([v for v in ("number", "expver") if v in ds.variables])
    out = xr.Dataset(
        {
            "t2m": ds["t2m"] - 273.15,
            "u10": ds["u10"],
            "v10": ds["v10"],
        }
    )
    out["ws10"] = np.hypot(out["u10"], out["v10"])
    out["t2m"].attrs["units"] = "degC"
    out["ws10"].attrs["units"] = "m s-1"
    return out


def _months(first: str, last: str):
    current = pd.Period(first, freq="M")
    end = pd.Period(last, freq="M")
    while current <= end:
        yield str(current)
        current += 1


def _month_end(month: str) -> date:
    return pd.Period(month, freq="M").end_time.date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.ingest.era5")
    sub = parser.add_subparsers(dest="command", required=True)
    refresh_parser = sub.add_parser("refresh", help="download from [era5] start to the latest available month")
    pull_parser = sub.add_parser("pull", help="download an explicit month range (YYYY-MM YYYY-MM)")
    pull_parser.add_argument("first")
    pull_parser.add_argument("last")
    for p in (refresh_parser, pull_parser):
        p.add_argument("--group", choices=[*GROUPS, "all"], default="all",
                       help="core (temperature, wind), extra (solar radiation, precipitation) or all")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = create_config()
    area = [x.strip() for x in config["era5"]["area"].split(",")]
    for group in (GROUPS if args.group == "all" else [args.group]):
        ingestor = ERA5Ingestor(resolve_path(config, "storage", "raw_dir"), area, group=group)
        if args.command == "refresh":
            ingestor.refresh(config["era5"]["start"])
        else:
            ingestor.pull(args.first, args.last)
    return 0


if __name__ == "__main__":
    sys.exit(main())
