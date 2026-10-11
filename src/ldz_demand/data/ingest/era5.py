"""
ERA5 ingestor (Copernicus Climate Data Store).

Hourly 2m temperature and 10m wind (u, v) over a GB box, one NetCDF file per month, archived under
raw_dir/era5/<year>/. Requires a free CDS account, ~/.cdsapirc with your API token, and the ERA5
licence accepted on the dataset page.

Final vs preliminary data: ERA5 is published with ~5 days' latency as preliminary "ERA5T", which
is replaced by final ERA5 about 2-3 months later (values can change slightly). Months older than
FINAL_AFTER_DAYS are downloaded once to era5_gb_YYYY-MM.nc and never fetched again. More recent
months are downloaded to a new era5t_gb_YYYY-MM_pulled_<UTC time>.nc on each pull; load_hourly
uses the final file when present, else the latest preliminary one.

gas_day_means turns hourly fields into gas-day means. A gas day runs 05:00 to 05:00 UK local time
(04:00 UTC during BST). Only complete gas days are returned: 24 hours, or 23 / 25 for the gas
days spanning the spring / autumn clock changes.

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
FINAL_AFTER_DAYS = 90  # months ending longer ago than this are treated as final ERA5
LATENCY_DAYS = 6  # ERA5T is available ~5 days behind real time
GAS_DAY_START_HOUR = 5  # UK local time
UK_TZ = "Europe/London"

FINAL_NAME = re.compile(r"era5_gb_(\d{4}-\d{2})\.nc")
PRELIM_NAME = re.compile(r"era5t_gb_(\d{4}-\d{2})_pulled_(\w+)\.nc")


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
    """

    def __init__(self, raw_dir: Path, area, client=None) -> None:
        self.raw_dir = Path(raw_dir) / "era5"
        self.area = [float(x) for x in area]
        self._client = client

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
            else:
                pulled = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                path = self.raw_dir / month[:4] / f"era5t_gb_{month}_pulled_{pulled}.nc"
            self.download(month, path, today)
            downloaded.append(path)
        return downloaded

    def refresh(self, start: str, today: date | None = None) -> list[Path]:
        """Download everything from start to the latest available month."""
        today = today or date.today()
        latest = (today - timedelta(days=LATENCY_DAYS)).strftime("%Y-%m")
        return self.pull(start, latest, today)

    def final_path(self, month: str) -> Path:
        return self.raw_dir / month[:4] / f"era5_gb_{month}.nc"

    def download(self, month: str, path: Path, today: date) -> None:
        year, mon = month.split("-")
        last_day = min(_month_end(month), today - timedelta(days=LATENCY_DAYS)).day
        request = {
            "product_type": ["reanalysis"],
            "variable": VARIABLES,
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
        logger.info(f"{month}: requesting {last_day} days from CDS (queued requests can take minutes)")
        self.client.retrieve(DATASET, request, str(tmp))
        tmp.rename(path)
        logger.info(f"{month}: saved {path}")


def is_final(month: str, today: date) -> bool:
    return _month_end(month) < today - timedelta(days=FINAL_AFTER_DAYS)


def month_files(raw_dir: Path) -> dict[str, Path]:
    """month -> file to use: the final file if present, else the latest preliminary pull."""
    chosen: dict[str, tuple[int, str, Path]] = {}
    for path in sorted((Path(raw_dir) / "era5").rglob("*.nc")):
        if m := FINAL_NAME.fullmatch(path.name):
            rank = (1, "")
        elif m := PRELIM_NAME.fullmatch(path.name):
            rank = (0, m.group(2))
        else:
            continue
        month = m.group(1)
        if month not in chosen or rank > chosen[month][:2]:
            chosen[month] = (*rank, path)
    return {month: entry[2] for month, entry in sorted(chosen.items())}


def load_hourly(raw_dir: Path, first: str | None = None, last: str | None = None) -> xr.Dataset:
    """
    Hourly t2m (degC), u10, v10 and wind speed ws10 (m/s) on (time, latitude, longitude), UTC.
    """
    files = [p for m, p in month_files(raw_dir).items() if (first is None or m >= first) and (last is None or m <= last)]
    if not files:
        raise FileNotFoundError(f"No ERA5 files under {Path(raw_dir) / 'era5'} for {first}..{last}")
    ds = xr.concat([_standardise(xr.open_dataset(p)) for p in files], dim="time")
    ds = ds.sortby("time")
    return ds.isel(time=~ds.get_index("time").duplicated())


def gas_day_means(hourly: xr.Dataset) -> xr.Dataset:
    """Mean of each variable over each complete UK gas day (05:00-05:00 local). Index: gas_day."""
    utc = pd.DatetimeIndex(hourly["time"].values).tz_localize("UTC")
    # Shift on the local wall clock (naive), not in absolute time, so 05:00 BST maps to its own day
    local = utc.tz_convert(UK_TZ).tz_localize(None)
    gas_day = (local - pd.Timedelta(hours=GAS_DAY_START_HOUR)).normalize()
    labelled = hourly.assign_coords(gas_day=("time", gas_day))
    counts = pd.Series(1, index=gas_day).groupby(level=0).size()
    complete = counts.index[counts == _gas_day_hours(counts.index)]
    daily = labelled.groupby("gas_day").mean("time")
    return daily.sel(gas_day=daily["gas_day"].isin(complete))


def _gas_day_hours(gas_days: pd.DatetimeIndex) -> np.ndarray:
    """Real length in hours of each gas day: 24, or 23 / 25 across the clock changes."""
    starts = (gas_days + pd.Timedelta(hours=GAS_DAY_START_HOUR)).tz_localize(UK_TZ)
    ends = (gas_days + pd.Timedelta(days=1, hours=GAS_DAY_START_HOUR)).tz_localize(UK_TZ)
    return ((ends - starts) / pd.Timedelta(hours=1)).to_numpy().round().astype(int)


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
    sub.add_parser("refresh", help="download from [era5] start to the latest available month")
    pull_parser = sub.add_parser("pull", help="download an explicit month range (YYYY-MM YYYY-MM)")
    pull_parser.add_argument("first")
    pull_parser.add_argument("last")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = create_config()
    area = [x.strip() for x in config["era5"]["area"].split(",")]
    ingestor = ERA5Ingestor(resolve_path(config, "storage", "raw_dir"), area)
    if args.command == "refresh":
        ingestor.refresh(config["era5"]["start"])
    else:
        ingestor.pull(args.first, args.last)
    return 0


if __name__ == "__main__":
    sys.exit(main())
