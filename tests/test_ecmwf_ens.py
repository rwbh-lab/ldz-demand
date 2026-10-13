from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ldz_demand.data.ingest.ecmwf_ens import ENSIngestor, archived_runs, crop, load_run, parse_steps

AREA = [61, -8.5, 49.5, 2.0]
RUN = datetime(2026, 10, 12, 0)


def global_step(step: int, members=(1, 2, 3)) -> xr.Dataset:
    """A step shaped like the open-data fields: a wider grid than GB, latitudes north to south."""
    lat = np.arange(63.0, 47.75, -0.25)
    lon = np.arange(-12.0, 4.25, 0.25)
    shape = (len(members), len(lat), len(lon))
    return xr.Dataset(
        {"t2m": (("number", "latitude", "longitude"), np.full(shape, 280.15 + step / 10)),
         "u10": (("number", "latitude", "longitude"), np.full(shape, 3.0)),
         "v10": (("number", "latitude", "longitude"), np.full(shape, 4.0))},
        coords={"number": list(members), "latitude": lat, "longitude": lon,
                "step": np.timedelta64(step, "h"), "valid_time": np.datetime64(RUN) + np.timedelta64(step, "h")})


class FakeClient:
    def __init__(self, fail_at: int | None = None, latest: datetime = RUN):
        self.requests, self.fail_at, self._latest = [], fail_at, latest

    def retrieve(self, target, step, **request):
        if step == self.fail_at:
            raise ConnectionError("network dropped")
        self.requests.append((step, request))
        Path(target).write_text(str(step))  # stands in for the GRIB download

    def latest(self, **request):
        return self._latest


def read_fake(path: Path) -> xr.Dataset:
    return global_step(int(Path(path).read_text()))


def ingestor(tmp_path, client, steps=(0, 3, 360)):
    return ENSIngestor(tmp_path / "raw", AREA, steps=list(steps), client=client, reader=read_fake, pause=0)


def test_parse_steps():
    steps = parse_steps("0-144/3,150-360/6")
    assert len(steps) == 85 and steps[:3] == [0, 3, 6] and steps[48:51] == [144, 150, 156] and steps[-1] == 360
    assert parse_steps("0, 24-48/24") == [0, 24, 48]


def test_pull_crops_each_step_to_gb_and_keeps_no_global_files(tmp_path):
    client = FakeClient()
    path = ingestor(tmp_path, client).pull(RUN)

    assert path == tmp_path / "raw" / "ecmwf_ens" / "2026" / "ens_gb_20261012_00z.nc"
    ds = xr.open_dataset(path)
    assert dict(ds.sizes) == {"step": 3, "number": 3, "latitude": 47, "longitude": 43}
    assert float(ds["latitude"][0]) == 61.0 and float(ds["longitude"][0]) == -8.5
    assert ds["t2m"].dtype == np.float32 and ds.attrs["run"] == "2026-10-12T00:00Z"
    assert [s for s, _ in client.requests] == [0, 3, 360]
    assert client.requests[0][1]["type"] == "pf" and client.requests[0][1]["param"] == ["2t", "10u", "10v"]
    assert not list((tmp_path / "raw").rglob("*.grib2")) and not (tmp_path / "raw" / "ecmwf_ens" / "partial" / "20261012_00z").exists()


def test_an_interrupted_run_resumes_from_its_saved_steps(tmp_path):
    with pytest.raises(ConnectionError):
        ingestor(tmp_path, FakeClient(fail_at=360)).pull(RUN)
    assert not archived_runs(tmp_path / "raw")  # no run file until every step is in
    saved = sorted(p.name for p in (tmp_path / "raw" / "ecmwf_ens" / "partial" / "20261012_00z").glob("*.nc"))
    assert saved == ["step_000.nc", "step_003.nc"]

    client = FakeClient()
    ingestor(tmp_path, client).pull(RUN)
    assert [s for s, _ in client.requests] == [360]  # only the missing step is downloaded again
    assert list(archived_runs(tmp_path / "raw")) == [RUN]


def test_refresh_fetches_missing_recent_runs_and_carries_on_past_failures(tmp_path):
    ing = ingestor(tmp_path, FakeClient(latest=datetime(2026, 10, 13)), steps=(0,))
    ing.pull(datetime(2026, 10, 12))  # already archived

    calls = []
    original = ing.pull

    def pull(run):
        calls.append(run)
        if run == datetime(2026, 10, 10):
            raise ValueError("no longer on the portal")
        return original(run)

    ing.pull = pull
    done = ing.refresh(days_back=3)
    assert calls == [datetime(2026, 10, 10), datetime(2026, 10, 11), datetime(2026, 10, 13)]
    assert len(done) == 2 and set(archived_runs(tmp_path / "raw")) == {datetime(2026, 10, d) for d in (11, 12, 13)}


def test_crop_handles_0_to_360_longitudes_and_refuses_a_short_grid():
    ds = global_step(0)
    shifted = ds.assign_coords(longitude=ds["longitude"] % 360).sortby("longitude")
    out = crop(shifted, AREA)
    assert out.sizes["longitude"] == 43 and float(out["longitude"].min()) == -8.5
    with pytest.raises(ValueError, match="expected"):
        crop(ds.sel(latitude=slice(60, 50)), AREA)


def test_load_run_gives_era5_conventions(tmp_path):
    ingestor(tmp_path, FakeClient()).pull(RUN)
    ds = load_run(tmp_path / "raw", RUN)
    assert set(ds.data_vars) == {"t2m", "u10", "v10", "ws10"} and "time" in ds.dims
    assert pd.Timestamp(ds["time"].values[-1]) == pd.Timestamp("2026-10-27 00:00")  # 360 h after the run
    assert float(ds["t2m"].isel(time=0).mean()) == pytest.approx(7.0, abs=1e-4)  # 280.15 K
    assert np.allclose(ds["ws10"], 5.0)
