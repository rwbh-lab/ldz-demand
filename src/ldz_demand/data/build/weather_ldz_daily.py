"""
Builds weather_ldz_daily: ERA5 gas-day weather per LDZ, for every membership x weighting variant.

For each month in the ERA5 archive: hourly fields (that month plus the next, so the month's last gas
day is complete) -> gas-day statistics per cell (gas_day.DAILY_STATS: means of temperature, wind and
solar radiation, the minimum and maximum hourly temperature, total precipitation; wind speed is
computed hourly, before averaging) -> one weighted mean per LDZ and variant, with the cell weights in
geo/data/ldz_cell_weights.csv (see ldz_demand.geo.grid_weights). Solar radiation and precipitation
need the ERA5 "extra" files; days without them have temperature and wind only. Rows are written with replace, so rebuilding is safe and idempotent;
a month whose preliminary ERA5T data has since gone final is simply rebuilt.

Run as a script:
    python -m ldz_demand.data.build.weather_ldz_daily                  # every month in the archive
    python -m ldz_demand.data.build.weather_ldz_daily --since 2026-08  # that month onwards
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ldz_demand.config import create_config, resolve_path
from ldz_demand.data.build.gas_day import gas_day_labels, gas_day_stats
from ldz_demand.data.datasets import WEATHER_LDZ_DAILY
from ldz_demand.data.ingest.era5 import FINAL_NAME, load_hourly, month_files
from ldz_demand.data.store import Store, get_store

logger = logging.getLogger(__name__)

VARIABLES = {"t2m": "degC", "t2m_heat": "degC", "ws10": "m s-1", "tmin": "degC", "tmax": "degC", "ssrd": "W m-2",
             "tp": "mm"}  # t2m_heat: the gas-day temperature weighted to the heating hours (gas_day.hour_weights)
# the cell weights to use for each variable (the weights table has temperature and wind; WM takes its
# wind from a different station): everything that isn't wind uses the temperature weights
WEIGHTS_FOR = {"ws10": "ws10"}
KEY = ["ldz", "membership", "weighting"]


def weight_arrays(weights: pd.DataFrame, lats, lons) -> dict[str, tuple[pd.DataFrame, np.ndarray]]:
    """Per variable: (variant keys, weights on the grid as an array [variant, lat, lon])."""
    lat_index = {round(float(v), 2): i for i, v in enumerate(lats)}
    lon_index = {round(float(v), 2): i for i, v in enumerate(lons)}
    missing = (set(weights["lat"].round(2)) - set(lat_index)) | (set(weights["lon"].round(2)) - set(lon_index))
    if missing:
        raise ValueError(f"cell weights reach outside the ERA5 grid (e.g. {sorted(missing)[:3]}); rebuild the weights")
    out = {}
    for variable in VARIABLES:
        w = weights[weights["variable"] == WEIGHTS_FOR.get(variable, "t2m")]
        keys = w[KEY].drop_duplicates().reset_index(drop=True)
        k_index = {tuple(k): i for i, k in enumerate(keys.itertuples(index=False))}
        arr = np.zeros((len(keys), len(lats), len(lons)))
        for r in w.itertuples():
            arr[k_index[(r.ldz, r.membership, r.weighting)], lat_index[round(r.lat, 2)], lon_index[round(r.lon, 2)]] += r.weight
        out[variable] = (keys, arr)
    return out


def ldz_weather(daily: xr.Dataset, weights: pd.DataFrame) -> pd.DataFrame:
    """Weighted LDZ means of gas-day fields (dims gas_day, latitude, longitude) as long rows."""
    arrays = weight_arrays(weights, daily["latitude"].values, daily["longitude"].values)
    frames = []
    for variable, unit in VARIABLES.items():
        if variable not in daily:
            continue
        keys, w = arrays[variable]
        values = np.einsum("dij,kij->dk", daily[variable].transpose("gas_day", "latitude", "longitude").values, w)
        frame = pd.DataFrame(values, index=pd.DatetimeIndex(daily["gas_day"].values, name="gas_day"),
                             columns=pd.MultiIndex.from_frame(keys))
        long = frame.stack(KEY, future_stack=True).rename("value").reset_index()
        frames.append(long.assign(variable=variable, unit=unit))
    out = pd.concat(frames, ignore_index=True)
    bad = out["value"].isna()
    if bad.any():
        missing = out[bad]
        detail = ", ".join(f"{v} on {d}" for v, d in sorted(
            missing.groupby("variable")["gas_day"].agg(lambda g: _days(g)).items()))
        if set(missing["variable"]) <= {"ssrd", "tp"}:  # expected at the edge of the extra files
            logger.info(f"Skipped {bad.sum()} LDZ values without complete data ({detail}): solar radiation / "
                        "precipitation need the ERA5 extra files for every hour of the gas day")
        else:
            logger.warning(f"Skipped {bad.sum()} LDZ values with missing ERA5 values ({detail})")
    return out[~bad]


def _days(gas_days: pd.Series) -> str:
    days = sorted(pd.DatetimeIndex(gas_days.unique()).date)
    return f"{days[0]}" if len(days) == 1 else f"{len(days)} gas days {days[0]}..{days[-1]}"


class WeatherLdzDailyBuilder:
    """
    Parameters
    ----------
    store : Store
        Destination for WEATHER_LDZ_DAILY.
    raw_dir : Path
        Raw archive root (ERA5 files under raw_dir/era5).
    weights : DataFrame, optional
        Cell weights; defaults to the committed geo/data/ldz_cell_weights.csv.
    """

    def __init__(self, store: Store, raw_dir: Path, weights: pd.DataFrame | None = None) -> None:
        self.store = store
        self.raw_dir = Path(raw_dir)
        if weights is None:
            from ldz_demand.geo import grid_weights

            weights = grid_weights.load()
        self.weights = weights

    def build(self, since: str | None = None) -> int:
        """Build every archived month (from `since`, YYYY-MM, if given). Returns rows written."""
        files = month_files(self.raw_dir)
        months = [m for m in files if since is None or m >= since]
        if not months:
            logger.warning(f"No ERA5 months under {self.raw_dir / 'era5'}" + (f" from {since}" if since else ""))
            return 0
        written = 0
        for month in months:
            written += self.build_month(month, files)
        return written

    def build_month(self, month: str, files: dict[str, Path] | None = None) -> int:
        files = files or month_files(self.raw_dir)
        following = str(pd.Period(month, freq="M") + 1)
        hourly = load_hourly(self.raw_dir, month, following if following in files else month)
        daily = gas_day_stats(hourly)
        in_month = pd.DatetimeIndex(daily["gas_day"].values).to_period("M") == pd.Period(month, freq="M")
        daily = daily.isel(gas_day=in_month)
        if daily.sizes["gas_day"] == 0:
            logger.info(f"{month}: no complete gas days yet")
            return 0
        rows = ldz_weather(daily, self.weights)
        rows["source"] = self._sources(hourly, files).reindex(pd.DatetimeIndex(rows["gas_day"])).to_numpy()
        n = self.store.write(WEATHER_LDZ_DAILY, rows, on_conflict="replace")
        logger.info(f"{month}: {daily.sizes['gas_day']} gas days, {n} rows")
        return n

    @staticmethod
    def _sources(hourly: xr.Dataset, files: dict[str, Path]) -> pd.Series:
        """'era5' for gas days made only of final ERA5 hours, else 'era5t' (preliminary)."""
        times = pd.DatetimeIndex(hourly["time"].values)
        final = pd.Series([bool(FINAL_NAME.fullmatch(files[m].name)) for m in times.strftime("%Y-%m")], index=times)
        gas_day, _ = gas_day_labels(times)
        all_final = final.groupby(gas_day).all()
        return all_final.map({True: "era5", False: "era5t"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.build.weather_ldz_daily")
    parser.add_argument("--since", help="first month to build, YYYY-MM (default: every archived month)")
    parser.add_argument("--recent", type=int, metavar="MONTHS",
                        help="build this month and the MONTHS before it (for scheduled jobs; overrides --since)")
    args = parser.parse_args(argv)
    if args.recent is not None:
        args.since = (pd.Timestamp.today().to_period("M") - args.recent).strftime("%Y-%m")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = create_config()
    builder = WeatherLdzDailyBuilder(get_store(config), resolve_path(config, "storage", "raw_dir"))
    builder.build(args.since)
    return 0


if __name__ == "__main__":
    sys.exit(main())
