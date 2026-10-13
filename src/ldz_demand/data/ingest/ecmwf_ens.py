"""
ECMWF open-data ensemble (ENS) ingestor — download each 00z run, crop it to GB, archive it.

The 50 perturbed members, 2 m temperature and 10 m wind (u, v), 0.25°, out to 15 days (3-hourly to
day 6, then 6-hourly). Open data under CC-BY-4.0, no registration. The open-data ensemble files carry
the perturbed members only (type pf, numbers 1-50): the control forecast is not published there.

The published files are global (one file per step, every variable and member, ~6 GB), so each
step's fields are downloaded by byte range (~115 MB for our three variables), cropped to the
[ecmwf_ens] area straight away and the global download deleted: only GB is ever kept. A full run is
~10 GB downloaded (~20 minutes at ~13 MB/s) and ~40 MB stored. Steps are saved as they finish, so an interrupted run resumes
where it stopped; the run file appears only once every step is in.

Archived as raw_dir/ecmwf_ens/<year>/ens_gb_YYYYMMDD_HHz.nc — values as delivered (t2m in K,
u10 / v10 in m/s) on (step, number, latitude, longitude); load_run() converts to the ERA5 conventions.

Run as a script:
    python -m ldz_demand.data.ingest.ecmwf_ens refresh                 # the latest runs not yet archived
    python -m ldz_demand.data.ingest.ecmwf_ens pull 2026-10-12         # one run (must still be published)
    python -m ldz_demand.data.ingest.ecmwf_ens status                  # archived runs
"""

import argparse
import logging
import os
import shutil
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ldz_demand.config import create_config, resolve_path

logger = logging.getLogger(__name__)

PARAMS = ["2t", "10u", "10v"]
VARIABLES = {"2t": "t2m", "10u": "u10", "10v": "v10"}  # GRIB short name -> our name (as cfgrib names them)
STEPS = list(range(0, 145, 3)) + list(range(150, 361, 6))  # hours: 3-hourly to 144, 6-hourly to 360
RUN_HOUR = 0
DAYS_BACK = 3  # refresh looks for runs this many days back from the latest (the portal keeps a few days)
ATTRIBUTION = "Contains ECMWF open data (CC-BY-4.0), https://www.ecmwf.int/en/forecasts/datasets/open-data"


def parse_steps(text: str) -> list[int]:
    """'0-144/3,150-360/6' -> [0, 3, ..., 144, 150, ..., 360]."""
    steps = []
    for part in text.split(","):
        span, _, by = part.strip().partition("/")
        first, _, last = span.partition("-")
        steps += list(range(int(first), int(last or first) + 1, int(by or 1)))
    return sorted(set(steps))


class ENSIngestor:
    """
    Parameters
    ----------
    raw_dir : Path
        Raw archive root; runs go to raw_dir/ecmwf_ens/<year>/.
    area : sequence of float
        north, west, south, east in degrees (the ERA5 box, so the grids match cell for cell).
    source : str
        ecmwf-opendata source: "ecmwf" (the open-data portal) or a mirror ("aws", "azure", "google").
    client, reader : optional
        Injectable for testing: an ecmwf.opendata.Client-like object with retrieve() and latest(), and a
        function reading one downloaded step file into a Dataset (defaults to read_step).
    """

    def __init__(self, raw_dir: Path, area, source: str = "ecmwf", run_hour: int = RUN_HOUR,
                 steps: list[int] | None = None, client=None, reader=None, pause: float = 1.0) -> None:
        self.root = Path(raw_dir) / "ecmwf_ens"
        self.area = [float(x) for x in area]
        self.source = source
        self.run_hour = run_hour
        self.steps = steps or STEPS
        self._client = client
        self.reader = reader or read_step
        self.pause = pause

    @property
    def client(self):
        if self._client is None:
            from ecmwf.opendata import Client

            # fail within minutes, not hours (the client's defaults are 500 retries, 2 minutes apart)
            self._client = Client(source=self.source, model="ifs", resol="0p25", maximum_retries=5, retry_after=30)
            if os.environ.get("TQDM_DISABLE"):
                _quiet_downloads()
        return self._client

    # --- paths ---------------------------------------------------------------------------------

    def run_path(self, run: datetime) -> Path:
        return self.root / f"{run:%Y}" / f"ens_gb_{run:%Y%m%d}_{run:%H}z.nc"

    def partial_dir(self, run: datetime) -> Path:
        return self.root / "partial" / f"{run:%Y%m%d}_{run:%H}z"

    # --- what to fetch -------------------------------------------------------------------------

    def latest_run(self) -> datetime:
        """The most recent run whose last step is published."""
        date = self.client.latest(time=self.run_hour, stream="enfo", type="pf", step=max(self.steps), param="2t")
        return pd.Timestamp(date).to_pydatetime().replace(tzinfo=None)

    def refresh(self, days_back: int = DAYS_BACK) -> list[Path]:
        """Archive the latest published run and any of the previous `days_back` runs that are missing."""
        latest = self.latest = self.latest_run()
        done = []
        for k in range(days_back, -1, -1):
            run = latest - timedelta(days=k)
            if self.run_path(run).exists():
                logger.info(f"{run:%Y-%m-%d %Hz}: archived already")
                continue
            try:
                done.append(self.pull(run))
            except Exception as exc:  # an older run may have left the portal; keep going with the rest
                logger.warning(f"{run:%Y-%m-%d %Hz}: not archived ({type(exc).__name__}: {exc})")
        return done

    # --- download ------------------------------------------------------------------------------

    def pull(self, run: datetime) -> Path:
        """Download, crop and archive every step of one run. Resumes from the steps already saved."""
        final = self.run_path(run)
        if final.exists():
            return final
        work = self.partial_dir(run)
        work.mkdir(parents=True, exist_ok=True)
        started = datetime.now(timezone.utc)
        for i, step in enumerate(self.steps, 1):
            saved = work / f"step_{step:03d}.nc"
            if saved.exists():
                continue
            grib = work / f"step_{step:03d}.grib2"
            self.client.retrieve(date=run.strftime("%Y-%m-%d"), time=run.hour, stream="enfo", type="pf",
                                 param=PARAMS, step=step, target=str(grib))
            crop(self.reader(grib), self.area).to_netcdf(saved.with_suffix(".part"))
            saved.with_suffix(".part").rename(saved)
            grib.unlink()  # never keep the global fields
            if i % 10 == 0 or i == len(self.steps):
                logger.info(f"{run:%Y-%m-%d %Hz}: {i}/{len(self.steps)} steps")
            time.sleep(self.pause)
        self._combine(run, work, final, started)
        shutil.rmtree(work)
        logger.info(f"{run:%Y-%m-%d %Hz}: archived -> {final} ({final.stat().st_size / 1e6:.0f} MB)")
        return final

    def _combine(self, run: datetime, work: Path, final: Path, started: datetime) -> None:
        parts = [xr.open_dataset(work / f"step_{s:03d}.nc") for s in self.steps]
        ds = xr.concat(parts, dim="step", coords=["valid_time"], compat="override").sortby("step")
        ds.attrs.update({
            "title": "ECMWF IFS ensemble (ENS), cropped to GB",
            "run": f"{run:%Y-%m-%dT%H:%M}Z", "source": self.source, "stream": "enfo", "type": "pf (members 1-50)",
            "params": ", ".join(PARAMS), "steps_h": ",".join(map(str, self.steps)),
            "area_nwse": ", ".join(map(str, self.area)),
            "downloaded": f"{started:%Y-%m-%dT%H:%M}Z to {datetime.now(timezone.utc):%Y-%m-%dT%H:%M}Z",
            "attribution": ATTRIBUTION,
        })
        encoding = {v: {"zlib": True, "complevel": 4, "dtype": "float32"} for v in ds.data_vars}
        final.parent.mkdir(parents=True, exist_ok=True)
        part = final.with_suffix(".part")
        ds.load().to_netcdf(part, encoding=encoding)
        for p in parts:
            p.close()
        part.rename(final)


# --- GRIB reading and cropping --------------------------------------------------------------------

def read_step(path: Path) -> xr.Dataset:
    """One downloaded step as t2m, u10, v10 on (number, latitude, longitude)."""
    import cfgrib

    pieces: dict[str, list[xr.DataArray]] = {v: [] for v in VARIABLES.values()}
    step = valid_time = None
    with warnings.catch_warnings():  # cfgrib's own merge triggers an xarray FutureWarning
        warnings.simplefilter("ignore", FutureWarning)
        datasets = cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""})
    for ds in datasets:
        for name in pieces:
            if name not in ds:
                continue
            da = ds[name]
            if "number" not in da.dims:  # a single member (e.g. a control forecast) comes as a scalar number
                da = da.expand_dims("number")
            step, valid_time = da["step"].values, da["valid_time"].values
            pieces[name].append(da.reset_coords([c for c in da.coords if c not in da.dims], drop=True))
    missing = [n for n, p in pieces.items() if not p]
    if missing:
        raise ValueError(f"{path.name}: no {missing} in the downloaded fields")
    out = xr.Dataset({n: xr.concat(p, dim="number").sortby("number") for n, p in pieces.items()})
    return out.assign_coords(step=step, valid_time=valid_time)


def _quiet_downloads() -> None:
    """No per-file progress bars: multiurl draws them with disable=False, so TQDM_DISABLE alone can't."""
    import functools

    import ecmwf.opendata.client
    import multiurl
    from multiurl.base import NoBar

    ecmwf.opendata.client.download = functools.partial(multiurl.download, progress_bar=NoBar)


def crop(ds: xr.Dataset, area) -> xr.Dataset:
    """Cut to the north, west, south, east box (inclusive), latitudes north to south like ERA5."""
    north, west, south, east = area
    ds = ds.assign_coords(latitude=ds["latitude"].round(3), longitude=ds["longitude"].round(3))
    if float(ds["longitude"].max()) > 180:  # 0..360 grids
        ds = ds.assign_coords(longitude=((ds["longitude"] + 180) % 360) - 180).sortby("longitude")
    ds = ds.sortby("latitude", ascending=False)
    out = ds.sel(latitude=slice(north, south), longitude=slice(west, east))
    expected = (round((north - south) / 0.25) + 1, round((east - west) / 0.25) + 1)
    if (out.sizes["latitude"], out.sizes["longitude"]) != expected:
        raise ValueError(f"cropped grid is {out.sizes['latitude']}x{out.sizes['longitude']}, expected {expected}")
    return out


# --- reading the archive ----------------------------------------------------------------------

def archived_runs(raw_dir: Path) -> dict[datetime, Path]:
    out = {}
    for path in sorted((Path(raw_dir) / "ecmwf_ens").glob("*/ens_gb_*_*z.nc")):
        stamp = path.stem.removeprefix("ens_gb_")
        out[datetime.strptime(stamp, "%Y%m%d_%Hz")] = path
    return out


def load_run(raw_dir: Path, run: datetime) -> xr.Dataset:
    """
    One archived run in the ERA5 conventions: t2m (degC), u10, v10 and wind speed ws10 (m/s) on
    (time, number, latitude, longitude), time = valid time in UTC.
    """
    path = archived_runs(raw_dir)[run]
    ds = xr.open_dataset(path)
    ds = ds.swap_dims({"step": "valid_time"}).rename({"valid_time": "time"})
    out = xr.Dataset({"t2m": ds["t2m"] - 273.15, "u10": ds["u10"], "v10": ds["v10"]}, attrs=ds.attrs)
    out["ws10"] = np.hypot(out["u10"], out["v10"])
    out["t2m"].attrs["units"] = "degC"
    out["ws10"].attrs["units"] = "m s-1"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.ingest.ecmwf_ens")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("refresh", help="archive the latest published runs not yet archived")
    pull_parser = sub.add_parser("pull", help="archive one run, YYYY-MM-DD (it must still be published)")
    pull_parser.add_argument("date")
    sub.add_parser("status", help="list archived runs")
    args = parser.parse_args(argv)

    os.environ.setdefault("TQDM_DISABLE", "1")  # no per-file progress bars in scheduled logs
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = create_config()
    raw_dir = resolve_path(config, "storage", "raw_dir")
    section = config["ecmwf_ens"]
    if args.command == "status":
        runs = archived_runs(raw_dir)
        for run, path in runs.items():
            print(f"{run:%Y-%m-%d %Hz}  {path.stat().st_size / 1e6:6.0f} MB  {path}")
        print(f"{len(runs)} runs archived")
        return 0
    ingestor = ENSIngestor(raw_dir, [x.strip() for x in section["area"].split(",")], source=section["source"],
                           run_hour=section.getint("run_hour"), steps=parse_steps(section["steps"]))
    if args.command == "refresh":
        ingestor.refresh(section.getint("days_back"))
        if not ingestor.run_path(ingestor.latest).exists():  # a non-zero exit is what makes a scheduler alert
            logger.error(f"latest run {ingestor.latest:%Y-%m-%d %Hz} was not archived")
            return 1
    else:
        ingestor.pull(datetime.strptime(args.date, "%Y-%m-%d").replace(hour=ingestor.run_hour))
    return 0


if __name__ == "__main__":
    sys.exit(main())
