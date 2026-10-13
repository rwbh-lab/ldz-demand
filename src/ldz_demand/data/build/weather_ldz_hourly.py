"""
Builds weather_ldz_hourly: ERA5 hourly weather per LDZ, for the [ldz_weather] detail_variants.

The hourly LDZ series behind weather_ldz_daily, kept so that ways of turning a day's weather into a
demand driver (flat mean, weighting the morning and evening heating peaks, ...) can be tested
without going back to the gridded archive. Same cell weights as weather_ldz_daily; only the detail
variants, to keep the table to a few million rows. Rows are written with replace, month by month.

Run as a script:
    python -m ldz_demand.data.build.weather_ldz_hourly                  # every month in the archive
    python -m ldz_demand.data.build.weather_ldz_hourly --since 2026-08  # that month onwards
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ldz_demand.config import create_config, resolve_path
from ldz_demand.data.build.weather_ldz_daily import KEY, VARIABLES, weight_arrays

# hourly values: temperature and wind at the hour; solar radiation (mean W m-2) and precipitation (mm)
# over the hour ending then (where the ERA5 extra files exist)
HOURLY_VARIABLES = {v: VARIABLES[v] for v in ("t2m", "ws10", "ssrd", "tp")}
from ldz_demand.data.datasets import WEATHER_LDZ_HOURLY
from ldz_demand.data.ingest.era5 import FINAL_NAME, load_hourly, month_files
from ldz_demand.data.store import Store, get_store

logger = logging.getLogger(__name__)


def ldz_hourly(hourly: xr.Dataset, weights: pd.DataFrame) -> pd.DataFrame:
    """Weighted LDZ means of hourly fields (dims time, latitude, longitude) as long rows."""
    arrays = weight_arrays(weights, hourly["latitude"].values, hourly["longitude"].values)
    frames = []
    for variable, unit in HOURLY_VARIABLES.items():
        if variable not in hourly:
            continue
        keys, w = arrays[variable]
        values = np.einsum("tij,kij->tk", hourly[variable].transpose("time", "latitude", "longitude").values, w)
        frame = pd.DataFrame(values, index=pd.DatetimeIndex(hourly["time"].values, name="time"),
                             columns=pd.MultiIndex.from_frame(keys))
        frames.append(frame.stack(KEY, future_stack=True).rename("value").reset_index().assign(variable=variable, unit=unit))
    out = pd.concat(frames, ignore_index=True)
    return out[out["value"].notna()]


class WeatherLdzHourlyBuilder:
    """
    Parameters
    ----------
    store : Store
        Destination for WEATHER_LDZ_HOURLY.
    raw_dir : Path
        Raw archive root (ERA5 files under raw_dir/era5).
    weights : DataFrame, optional
        Cell weights, already narrowed to the variants wanted; defaults to the committed weights
        narrowed to the [ldz_weather] detail_variants.
    """

    def __init__(self, store: Store, raw_dir: Path, weights: pd.DataFrame | None = None) -> None:
        self.store = store
        self.raw_dir = Path(raw_dir)
        if weights is None:
            from ldz_demand.geo import grid_weights

            weights = grid_weights.select(grid_weights.load(), grid_weights.detail_variants())
        self.weights = weights

    def build(self, since: str | None = None) -> int:
        files = month_files(self.raw_dir)
        months = [m for m in files if since is None or m >= since]
        if not months:
            logger.warning(f"No ERA5 months under {self.raw_dir / 'era5'}" + (f" from {since}" if since else ""))
            return 0
        written = 0
        for month in months:
            hourly = load_hourly(self.raw_dir, month, month)
            rows = ldz_hourly(hourly, self.weights)
            rows["source"] = "era5" if FINAL_NAME.fullmatch(files[month].name) else "era5t"
            n = self.store.write(WEATHER_LDZ_HOURLY, rows, on_conflict="replace")
            logger.info(f"{month}: {hourly.sizes['time']} hours, {n} rows")
            written += n
        return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.build.weather_ldz_hourly")
    parser.add_argument("--since", help="first month to build, YYYY-MM (default: every archived month)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = create_config()
    WeatherLdzHourlyBuilder(get_store(config), resolve_path(config, "storage", "raw_dir")).build(args.since)
    return 0


if __name__ == "__main__":
    sys.exit(main())
