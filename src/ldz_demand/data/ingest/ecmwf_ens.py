"""
ECMWF open-data ensemble (ENS) ingestor — download each 00z run, crop it to GB, archive it.

The 50 perturbed members, 0.25°, out to 15 days (3-hourly to day 6, then 6-hourly): 2 m temperature,
10 m wind (u, v), surface solar radiation (ssrd), total precipitation (tp), and the 2 m temperature
minimum / maximum over each step's period (mn2t3 / mx2t3 to 144 h, mn2t6 / mx2t6 after). Open data under
CC-BY-4.0, no registration. The open-data ensemble files carry the perturbed members only (type pf,
numbers 1-50): the control forecast is not published there.

The published files are global (one file per step, every variable and member, ~6 GB), so each
step's fields are downloaded by byte range (~270 MB for our variables), cropped to the [ecmwf_ens]
area straight away and the global download deleted: only GB is ever kept. A full run is ~23 GB
downloaded and ~100 MB stored. ECMWF's speed per connection varies (6-13 MB/s), so several steps download
at once ([ecmwf_ens] downloads); decoding runs one step at a time alongside, each field cropped as it is
decoded so memory stays small. Timings are logged so a slow machine shows whether downloads or decoding
are the limit. Steps are saved as they finish, so an interrupted run resumes
where it stopped; the run file appears only once every step is in.

Archived as raw_dir/ecmwf_ens/<year>/ens_gb_YYYYMMDD_HHz.nc — values as delivered on (step, number,
latitude, longitude): t2m, tmin, tmax in K; u10 / v10 in m/s; ssrd (J m-2) and tp (m) accumulated from
the start of the run; tmin / tmax over the period since the previous step (missing at step 0). Runs
archived before 2026-10-13 have temperature and wind only. load_run() converts to the ERA5 conventions.

Run as a script:
    python -m ldz_demand.data.ingest.ecmwf_ens refresh                 # the latest runs not yet archived
    python -m ldz_demand.data.ingest.ecmwf_ens pull 2026-10-12         # one run (must still be published)
    python -m ldz_demand.data.ingest.ecmwf_ens pull 2025-12-15 --source aws        # one past run, from a mirror
    python -m ldz_demand.data.ingest.ecmwf_ens backfill 2025-10-01 2026-03-31 --downloads 3  # past runs (AWS)

Past runs: the cloud mirrors keep the open data from 18 Jan 2023 (AWS); 0.25° with every variable above
from 1 Feb 2024 (0.4° and temperature, wind and precipitation only before). The mirrors throttle, so
fewer steps download at once there, and a throttled step waits longer and is tried more often.
    python -m ldz_demand.data.ingest.ecmwf_ens status                  # archived runs
"""

import argparse
import functools
import logging
import os
import shutil
import sys
import socket
import tempfile
import threading
import time
import warnings
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ldz_demand.config import create_config, resolve_path

logger = logging.getLogger(__name__)

PARAMS = ["2t", "10u", "10v"]                 # instantaneous: every step
ACCUMULATED = ["ssrd", "tp"]                    # from the start of the run: steps after 0
EXTREMES = {3: ["mn2t3", "mx2t3"], 6: ["mn2t6", "mx2t6"]}  # over the period since the last step
# cfgrib variable name -> our name
VARIABLES = {"t2m": "t2m", "u10": "u10", "v10": "v10", "ssrd": "ssrd", "tp": "tp",
             "mn2t3": "tmin", "mx2t3": "tmax", "mn2t6": "tmin", "mx2t6": "tmax"}
STORED = ["t2m", "u10", "v10", "ssrd", "tp", "tmin", "tmax"]
STEPS = list(range(0, 145, 3)) + list(range(150, 361, 6))  # hours: 3-hourly to 144, 6-hourly to 360
RUN_HOUR = 0
DAYS_BACK = 3  # refresh looks for runs this many days back from the latest (the portal keeps a few days)
DOWNLOADS = 6  # steps downloading at once (the portal allows 500 connections; per-connection speed varies)
# A stalled connection must fail, not hang: on 17 Oct 2026 two steps' downloads went silent and the job
# waited two days, blocking the next days' runs. Every socket read times out; each step is retried.
SOCKET_TIMEOUT_S = 120   # no data for this long -> the read fails
STEP_ATTEMPTS = 3        # tries per step before the run stops (its saved steps are kept for the next run)
RETRY_WAIT_S = 30.0
# The cloud mirrors throttle (AWS S3 answers "SlowDown" / HTTP 503 when requests come too fast, seen on
# 10 Nov 2026 with a few requests 8 s apart). Being throttled is not the step failing: wait longer, try more.
THROTTLE_ATTEMPTS = 8    # tries per step while the source says to slow down
THROTTLE_WAIT_S = 120.0  # times the attempt number
THROTTLE_MARKERS = ("slowdown", "slow down", "reduce your request rate", "503", "429", "service unavailable",
                    "too many requests")
MEMBERS = 50            # perturbed members per run (pf 1-50; no control)
# cfgrib skips a GRIB message it can't read ("skipping corrupted Message") and carries on, so a decoded step
# can lack members, or hold them as NaN, with no error. Seen on 10 Nov 2026 reading global files over an SMB
# share from a Mac: 2 of 50 members NaN in two steps, files intact when read again. Every step is checked;
# an incomplete one is downloaded and decoded again.
ATTRIBUTION = "Contains ECMWF open data (CC-BY-4.0), https://www.ecmwf.int/en/forecasts/datasets/open-data"


def step_params(step: int) -> list[str]:
    """
    The fields to download for a step. Extremes are published over the 3 h (to 144 h) or 6 h (after)
    before each step, so with the standard steps they cover the whole forecast; with a sparser step
    list they cover only the last 3 / 6 h before each step.
    """
    if step == 0:
        return list(PARAMS)
    return PARAMS + ACCUMULATED + EXTREMES[3 if step <= 144 else 6]


def is_throttled(exc: BaseException) -> bool:
    """Whether an error is the source asking us to slow down (HTTP 503 / 429, S3 SlowDown)."""
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) in (429, 503):
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in THROTTLE_MARKERS)


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
    members : int
        Members every step must hold (MEMBERS); a step decoded with fewer is downloaded again.
    scratch : Path, optional
        Where the global files go while they are decoded (a temporary folder made inside it, removed after).
        Default: beside the saved steps, in the run's partial folder on the archive. A local disk is faster
        and safer than a network share.
    client, reader : optional
        Injectable for testing: an ecmwf.opendata.Client-like object with retrieve() and latest(), and a
        function reading one downloaded step file into a Dataset (defaults to read_step).
    """

    def __init__(self, raw_dir: Path, area, source: str = "ecmwf", run_hour: int = RUN_HOUR,
                 steps: list[int] | None = None, client=None, reader=None, pause: float = 1.0,
                 downloads: int = DOWNLOADS, retry_wait: float = RETRY_WAIT_S,
                 throttle_wait: float = THROTTLE_WAIT_S, members: int = MEMBERS,
                 scratch: Path | None = None) -> None:
        self.root = Path(raw_dir) / "ecmwf_ens"
        self.area = [float(x) for x in area]
        self.source = source
        self.run_hour = run_hour
        self.steps = steps or STEPS
        self._client = client
        self._local = threading.local()
        self.reader = reader or functools.partial(read_step, area=self.area)
        self.pause = pause
        self.downloads = max(1, downloads)
        self.retry_wait = retry_wait
        self.throttle_wait = throttle_wait
        self.members = members
        self.scratch = Path(scratch) if scratch else None

    @property
    def client(self):
        """One client per thread (each has its own HTTP session); an injected client is shared."""
        if self._client is not None:
            return self._client
        if getattr(self._local, "client", None) is None:
            from ecmwf.opendata import Client

            # fail within minutes, not hours (the client's defaults are 500 retries, 2 minutes apart)
            self._local.client = Client(source=self.source, model="ifs", resol="0p25", maximum_retries=5, retry_after=30)
            _patch_downloads(quiet=bool(os.environ.get("TQDM_DISABLE")))
        return self._local.client

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

    def backfill(self, start: date, end: date) -> tuple[list[Path], list[datetime]]:
        """
        Archive every run from `start` to `end` (inclusive), oldest first, from a mirror that keeps past
        runs. Runs already archived are skipped and half-finished ones resume from their saved steps, so a
        stopped backfill is restarted with the same command. A run that fails is logged and left for the
        next attempt. Returns (archived, failed).
        """
        runs = [datetime.combine(d.date(), datetime.min.time()).replace(hour=self.run_hour)
                for d in pd.date_range(start, end, freq="D")]
        todo = [r for r in runs if not self.run_path(r).exists()]
        logger.info(f"backfill {start:%Y-%m-%d} to {end:%Y-%m-%d} from {self.source}: {len(runs)} runs, "
                    f"{len(runs) - len(todo)} archived already, {len(todo)} to fetch")
        done, failed = [], []
        t0 = time.monotonic()
        for k, run in enumerate(todo, 1):
            try:
                done.append(self.pull(run))
            except Exception as exc:  # keep going; the run is fetched on the next backfill
                failed.append(run)
                logger.warning(f"{run:%Y-%m-%d %Hz}: not archived ({type(exc).__name__}: {exc})")
            hours = (time.monotonic() - t0) / 3600
            logger.info(f"backfill: {k}/{len(todo)} runs tried, {len(done)} archived, {len(failed)} failed, "
                        f"{hours:.1f} h; about {hours / k * (len(todo) - k):.1f} h to go")
        if failed:
            logger.warning(f"backfill: {len(failed)} runs not archived: "
                           + ", ".join(f"{r:%Y-%m-%d}" for r in failed))
        return done, failed

    # --- download ------------------------------------------------------------------------------

    def pull(self, run: datetime) -> Path:
        """Download, crop and archive every step of one run. Resumes from the steps already saved."""
        final = self.run_path(run)
        if final.exists():
            return final
        work = self.partial_dir(run)
        work.mkdir(parents=True, exist_ok=True)
        socket.setdefaulttimeout(SOCKET_TIMEOUT_S)  # a backstop; the downloads also get it directly (_patch_downloads)
        started = datetime.now(timezone.utc)
        todo = [s for s in self.steps if not (work / f"step_{s:03d}.nc").exists()]
        timing = {"mb": 0.0, "download_s": 0.0, "process_s": 0.0, "done": len(self.steps) - len(todo)}
        t0 = time.monotonic()
        # downloads run in threads, several at once; each finished download is cropped, checked and saved
        # here, with the next downloads already started, so every connection stays busy while this thread
        # decodes (at most twice `downloads` global files on disk at a time). A step that decodes incomplete
        # goes back in the queue, up to STEP_ATTEMPTS times.
        gribs = Path(tempfile.mkdtemp(prefix=f"ens_{run:%Y%m%d}_", dir=self.scratch)) if self.scratch else work
        errors, decode_failures = [], {}
        try:
            with ThreadPoolExecutor(self.downloads) as pool:
                queue, running = list(todo), set()
                while running or (queue and not errors):
                    while queue and not errors and len(running) < self.downloads:
                        running.add(pool.submit(self._download, run, queue.pop(0), gribs))
                    finished, running = wait(running, return_when=FIRST_COMPLETED)
                    errors += [f.exception() for f in finished if f.exception() is not None]  # stop starting downloads
                    while queue and not errors and len(running) < self.downloads:
                        running.add(pool.submit(self._download, run, queue.pop(0), gribs))
                    for future in finished:
                        if future.exception() is not None:  # save the ones that did finish
                            continue
                        step, grib, mb, seconds = future.result()
                        t = time.monotonic()
                        saved = work / f"step_{step:03d}.nc"
                        try:
                            ds = crop(self.reader(grib), self.area)
                            check_step(ds, step, self.members)
                        except Exception as exc:
                            decode_failures[step] = decode_failures.get(step, 0) + 1
                            if decode_failures[step] == STEP_ATTEMPTS:
                                errors.append(exc)
                            else:
                                logger.warning(f"{run:%Y-%m-%d %Hz} step {step}: {exc.__class__.__name__} ({exc}); "
                                               f"downloading again ({decode_failures[step] + 1}/{STEP_ATTEMPTS})")
                                queue.insert(0, step)
                            continue
                        finally:
                            grib.unlink(missing_ok=True)  # never keep the global fields
                        ds.to_netcdf(saved.with_suffix(".part"))
                        saved.with_suffix(".part").rename(saved)
                        timing["mb"] += mb
                        timing["download_s"] += seconds
                        timing["process_s"] += time.monotonic() - t
                        timing["done"] += 1
                        if timing["done"] % 10 == 0 or timing["done"] == len(self.steps):
                            self._log_progress(run, timing, time.monotonic() - t0)
        finally:
            if gribs != work:
                shutil.rmtree(gribs, ignore_errors=True)
        if errors:
            raise errors[0]
        self._combine(run, work, final, started)
        shutil.rmtree(work)
        logger.info(f"{run:%Y-%m-%d %Hz}: archived -> {final} ({final.stat().st_size / 1e6:.0f} MB)")
        return final

    def _download(self, run: datetime, step: int, folder: Path) -> tuple[int, Path, float, float]:
        """One step's global fields -> folder/step_NNN.grib2, retried. Returns (step, path, MB, seconds)."""
        grib = folder / f"step_{step:03d}.grib2"
        t = time.monotonic()
        failures = throttles = 0  # counted apart: being told to slow down is not the step failing
        while True:
            try:
                self.client.retrieve(date=run.strftime("%Y-%m-%d"), time=run.hour, stream="enfo", type="pf",
                                     param=step_params(step), step=step, target=str(grib))
                break
            except Exception as exc:
                grib.unlink(missing_ok=True)  # never resume from a half-written file
                if is_throttled(exc):
                    throttles += 1
                    if throttles == THROTTLE_ATTEMPTS:
                        raise
                    wait_s, note = self.throttle_wait * throttles, f"throttled {throttles}/{THROTTLE_ATTEMPTS}"
                else:
                    failures += 1
                    if failures == STEP_ATTEMPTS:
                        raise
                    wait_s, note = self.retry_wait * failures, f"retrying ({failures + 1}/{STEP_ATTEMPTS})"
                logger.warning(f"{run:%Y-%m-%d %Hz} step {step}: {exc.__class__.__name__} ({exc}); "
                               f"{note}, waiting {wait_s:.0f} s")
                time.sleep(wait_s)
        seconds = time.monotonic() - t
        time.sleep(self.pause)
        return step, grib, grib.stat().st_size / 1e6, seconds

    def _log_progress(self, run: datetime, timing: dict, elapsed: float) -> None:
        mb, dl = timing["mb"], timing["download_s"]
        logger.info(f"{run:%Y-%m-%d %Hz}: {timing['done']}/{len(self.steps)} steps, {elapsed / 60:.1f} min; "
                    f"downloads {mb / max(dl, 1e-9) * self.downloads:.1f} MB/s across {self.downloads} "
                    f"({mb / max(dl, 1e-9):.1f} MB/s each), decode + crop {timing['process_s']:.0f} s in total")

    def _combine(self, run: datetime, work: Path, final: Path, started: datetime) -> None:
        parts = [xr.open_dataset(work / f"step_{s:03d}.nc") for s in self.steps]
        ds = xr.concat(parts, dim="step", coords=["valid_time"], compat="override").sortby("step")
        ds.attrs.update({
            "title": "ECMWF IFS ensemble (ENS), cropped to GB",
            "run": f"{run:%Y-%m-%dT%H:%M}Z", "source": self.source, "stream": "enfo", "type": "pf (members 1-50)",
            "params": ", ".join(PARAMS + ACCUMULATED) + ", mn2t3/mx2t3 (to 144 h), mn2t6/mx2t6 (after)",
            "steps_h": ",".join(map(str, self.steps)),
            "area_nwse": ", ".join(map(str, self.area)),
            "downloaded": f"{started:%Y-%m-%dT%H:%M}Z to {datetime.now(timezone.utc):%Y-%m-%dT%H:%M}Z",
            "attribution": ATTRIBUTION,
        })
        encoding = {v: {"zlib": True, "complevel": 4, "dtype": "float32", "_FillValue": np.float32("nan")}
                    for v in ds.data_vars}
        # whole hours, stated up front (xarray otherwise tries days, then falls back with a warning)
        encoding["step"] = {"units": "hours", "dtype": "int32"}
        encoding["valid_time"] = {"units": f"hours since {run:%Y-%m-%d %H:%M}", "dtype": "int32"}
        final.parent.mkdir(parents=True, exist_ok=True)
        part = final.with_suffix(".part")
        ds.load().to_netcdf(part, encoding=encoding)
        for p in parts:
            p.close()
        part.rename(final)


# --- GRIB reading and cropping --------------------------------------------------------------------

def read_step(path: Path, area=None) -> xr.Dataset:
    """
    One downloaded step on (number, latitude, longitude), with every STORED variable: those not
    published at this step (step 0: accumulations are 0, extremes don't exist yet) are filled. With
    `area`, each field is cropped as soon as it is decoded, so the globe is never held in memory.
    """
    import cfgrib

    pieces: dict[str, list[xr.DataArray]] = {v: [] for v in STORED}
    step = valid_time = None
    with warnings.catch_warnings():  # cfgrib's own merge triggers an xarray FutureWarning
        warnings.simplefilter("ignore", FutureWarning)
        datasets = cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""})
    for ds in datasets:
        for grib_name, name in VARIABLES.items():
            if grib_name not in ds:
                continue
            da = ds[grib_name]
            if area is not None:
                da = crop(da.to_dataset(name="v"), area)["v"].load()
            if "number" not in da.dims:  # a single member (e.g. a control forecast) comes as a scalar number
                da = da.expand_dims("number")
            if name in PARAMS_NAMES:
                step, valid_time = da["step"].values, da["valid_time"].values
            pieces[name].append(da.reset_coords([c for c in da.coords if c not in da.dims], drop=True))
    missing = [n for n in PARAMS_NAMES if not pieces[n]]
    if missing:
        raise ValueError(f"{path.name}: no {missing} in the downloaded fields")
    out = xr.Dataset({n: xr.concat(p, dim="number").sortby("number") for n, p in pieces.items() if p})
    template = out["t2m"]
    for name in STORED:
        if name not in out:  # step 0
            out[name] = xr.zeros_like(template) if name in ("ssrd", "tp") else xr.full_like(template, np.nan)
    return out[STORED].assign_coords(step=step, valid_time=valid_time)


PARAMS_NAMES = ["t2m", "u10", "v10"]


class IncompleteStep(ValueError):
    """A decoded step lacks members, or holds some as NaN (a GRIB message skipped while reading)."""


def check_step(ds: xr.Dataset, step: int, members: int = MEMBERS) -> None:
    """Raise IncompleteStep unless every variable has members 1..`members`, none of them all NaN.
    tmin/tmax are NaN throughout at step 0 (no period yet) and are not checked there."""
    expected = list(range(1, members + 1))
    if ds["number"].values.tolist() != expected:
        got = ds["number"].values.tolist()
        raise IncompleteStep(f"step {step}: {len(got)} of {members} members "
                             f"(missing {sorted(set(expected) - set(got))[:10]})")
    problems = []
    for name in ds.data_vars:
        if step == 0 and name in ("tmin", "tmax"):
            continue
        empty = ds[name].isnull().all([d for d in ds[name].dims if d != "number"])
        if bool(empty.any()):
            problems.append(f"{name} members {ds['number'].values[empty.values].tolist()}")
    if problems:
        raise IncompleteStep(f"step {step}: all NaN in " + "; ".join(problems))


def _patch_downloads(quiet: bool = True) -> None:
    """
    The client's downloads, with a read timeout (multiurl passes timeout=None to requests by default:
    wait forever, overriding the socket default) and, if quiet, no per-file progress bars (multiurl draws
    them with disable=False, so TQDM_DISABLE alone can't).
    """
    import functools

    import ecmwf.opendata.client
    import multiurl
    from multiurl.base import NoBar

    options = {"timeout": SOCKET_TIMEOUT_S, **({"progress_bar": NoBar} if quiet else {})}
    ecmwf.opendata.client.download = functools.partial(multiurl.download, **options)


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
    One archived run in the ERA5 conventions, on (time, number, latitude, longitude), time = valid time
    in UTC: t2m (degC), u10, v10 and wind speed ws10 (m/s); and where the run has them, over the period
    since the previous step (missing at the first step): ssrd (mean W m-2), tp (mm), tmin / tmax (degC).
    """
    path = archived_runs(raw_dir)[run]
    ds = xr.open_dataset(path)
    ds = ds.swap_dims({"step": "valid_time"}).rename({"valid_time": "time"})
    out = xr.Dataset({"t2m": ds["t2m"] - 273.15, "u10": ds["u10"], "v10": ds["v10"]}, attrs=ds.attrs)
    out["ws10"] = np.hypot(out["u10"], out["v10"])
    out["t2m"].attrs["units"] = "degC"
    out["ws10"].attrs["units"] = "m s-1"
    if "ssrd" in ds:
        seconds = (out["time"].diff("time") / np.timedelta64(1, "s")).astype(float)
        out["ssrd"] = (ds["ssrd"].diff("time") / seconds).reindex(time=out["time"])  # J m-2 -> mean W m-2
        out["tp"] = (ds["tp"].diff("time") * 1000).clip(min=0).reindex(time=out["time"])  # m -> mm
        out["tmin"], out["tmax"] = ds["tmin"] - 273.15, ds["tmax"] - 273.15
        for name, unit in (("ssrd", "W m-2"), ("tp", "mm"), ("tmin", "degC"), ("tmax", "degC")):
            out[name].attrs["units"] = unit
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.ingest.ecmwf_ens")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("refresh", help="archive the latest published runs not yet archived")
    pull_parser = sub.add_parser("pull", help="archive one run, YYYY-MM-DD (it must still be published)")
    pull_parser.add_argument("date")
    pull_parser.add_argument("--source", help="ecmwf (portal: the last few days) or a mirror (aws, azure, google: "
                                              "older runs); default [ecmwf_ens] source")
    backfill_parser = sub.add_parser("backfill", help="archive every run from START to END (YYYY-MM-DD) from a "
                                                      "mirror; rerun the same command to resume")
    backfill_parser.add_argument("start")
    backfill_parser.add_argument("end")
    backfill_parser.add_argument("--source", default="aws", help="a mirror keeping past runs: aws (default), "
                                                                 "azure, google")
    for p in (pull_parser, backfill_parser):
        p.add_argument("--downloads", type=int, help="steps downloading at once; default [ecmwf_ens] downloads "
                                                     "(use fewer on a mirror that throttles)")
        p.add_argument("--scratch", help="a local folder for the global files while they decode; default "
                                         "[ecmwf_ens] scratch, else the run's partial folder on the archive")
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
    source = getattr(args, "source", None) or section["source"]
    ingestor = ENSIngestor(raw_dir, [x.strip() for x in section["area"].split(",")], source=source,
                           run_hour=section.getint("run_hour"), steps=parse_steps(section["steps"]),
                           downloads=getattr(args, "downloads", None) or section.getint("downloads", DOWNLOADS),
                           scratch=getattr(args, "scratch", None) or section.get("scratch") or None)
    if args.command == "backfill":
        day = lambda s: datetime.strptime(s, "%Y-%m-%d")  # noqa: E731
        _, failed = ingestor.backfill(day(args.start), day(args.end))
        return 1 if failed else 0
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
