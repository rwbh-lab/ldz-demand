from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ldz_demand.data.ingest.era5 import ERA5Ingestor, is_final, load_hourly, month_files

AREA = [61, -8.5, 49.5, 2.0]


def cds_file(path, month: str, last_day: int, kelvin: float = 278.15):
    """Write a NetCDF shaped like a current CDS ERA5 download (valid_time, K, number/expver)."""
    times = pd.date_range(f"{month}-01", periods=24 * last_day, freq="h")
    lat, lon = np.array([52.0, 51.75]), np.array([-1.0, -0.75])
    shape = (len(times), len(lat), len(lon))
    ds = xr.Dataset(
        {
            "t2m": (("valid_time", "latitude", "longitude"), np.full(shape, kelvin)),
            "u10": (("valid_time", "latitude", "longitude"), np.full(shape, 3.0)),
            "v10": (("valid_time", "latitude", "longitude"), np.full(shape, 4.0)),
        },
        coords={"valid_time": times, "latitude": lat, "longitude": lon, "number": 0, "expver": ("valid_time", ["0001"] * len(times))},
    )
    ds.to_netcdf(path)


class FakeClient:
    def __init__(self):
        self.requests = []

    def retrieve(self, dataset, request, target):
        self.requests.append((dataset, request))
        month = f"{request['year'][0]}-{request['month'][0]}"
        cds_file(target, month, len(request["day"]))


@pytest.fixture
def ingestor(tmp_path):
    return ERA5Ingestor(tmp_path / "raw", AREA, client=FakeClient())


def test_final_months_download_once(ingestor):
    today = date(2026, 10, 11)
    paths = ingestor.pull("2025-12", "2026-01", today)
    assert [p.name for p in paths] == ["era5_gb_2025-12.nc", "era5_gb_2026-01.nc"]
    assert ingestor.pull("2025-12", "2026-01", today) == []

    dataset, request = ingestor.client.requests[0]
    assert dataset == "reanalysis-era5-single-levels"
    assert request["area"] == AREA
    assert len(request["time"]) == 24 and len(request["day"]) == 31


def test_recent_months_are_preliminary_and_truncated_to_available_days(ingestor, tmp_path):
    today = date(2026, 10, 11)
    paths = ingestor.refresh("2026-09", today)

    assert [p.name.split("_pulled_")[0] for p in paths] == ["era5t_gb_2026-09", "era5t_gb_2026-10"]
    october = ingestor.client.requests[-1][1]
    assert october["day"] == ["01", "02", "03", "04", "05"]  # today - 6 days latency
    assert not list(tmp_path.rglob("*.part"))


def test_is_final():
    assert is_final("2026-06", date(2026, 10, 11))
    assert not is_final("2026-08", date(2026, 10, 11))


def test_month_files_prefers_final_then_latest_preliminary(tmp_path):
    d = tmp_path / "era5" / "2026"
    d.mkdir(parents=True)
    for name in ["era5t_gb_2026-07_pulled_20260801T000000Z.nc", "era5_gb_2026-07.nc",
                 "era5t_gb_2026-08_pulled_20260901T000000Z.nc", "era5t_gb_2026-08_pulled_20261001T000000Z.nc",
                 "notes.nc"]:
        (d / name).touch()

    files = month_files(tmp_path)
    assert {m: p.name for m, p in files.items()} == {
        "2026-07": "era5_gb_2026-07.nc",
        "2026-08": "era5t_gb_2026-08_pulled_20261001T000000Z.nc",
    }


def test_load_hourly_standardises_units_and_names(tmp_path):
    (tmp_path / "era5" / "2026").mkdir(parents=True)
    cds_file(tmp_path / "era5" / "2026" / "era5_gb_2026-01.nc", "2026-01", 2)
    ds = load_hourly(tmp_path)

    assert set(ds.data_vars) == {"t2m", "u10", "v10", "ws10"}
    assert "time" in ds.dims
    assert float(ds["t2m"].isel(time=0, latitude=0, longitude=0)) == pytest.approx(5.0)
    assert float(ds["ws10"].isel(time=0, latitude=0, longitude=0)) == pytest.approx(5.0)


def extra_file(path, month: str, last_day: int):
    """Hourly accumulations as CDS delivers them: ssrd 360000 J m-2 (100 W m-2), tp 0.0005 m (0.5 mm) per hour."""
    times = pd.date_range(f"{month}-01", periods=24 * last_day, freq="h")
    lat, lon = np.array([52.0, 51.75]), np.array([-1.0, -0.75])
    shape = (len(times), len(lat), len(lon))
    xr.Dataset({"ssrd": (("valid_time", "latitude", "longitude"), np.full(shape, 360000.0)),
                "tp": (("valid_time", "latitude", "longitude"), np.full(shape, 0.0005))},
               coords={"valid_time": times, "latitude": lat, "longitude": lon}).to_netcdf(path)


class ExtraClient(FakeClient):
    def retrieve(self, dataset, request, target):
        self.requests.append((dataset, request))
        month = f"{request['year'][0]}-{request['month'][0]}"
        if "total_precipitation" in request["variable"]:
            extra_file(target, month, len(request["day"]))
        else:
            cds_file(target, month, len(request["day"]))


def test_extra_group_archives_separately_and_merges_on_load(tmp_path):
    today = date(2026, 10, 11)
    client = ExtraClient()
    core = ERA5Ingestor(tmp_path / "raw", AREA, client=client)
    extra = ERA5Ingestor(tmp_path / "raw", AREA, client=client, group="extra")
    core.pull("2026-01", "2026-02", today)
    assert [p.name for p in extra.pull("2026-01", "2026-01", today)] == ["era5x_gb_2026-01.nc"]
    assert client.requests[-1][1]["variable"] == ["surface_solar_radiation_downwards", "total_precipitation"]
    assert list(month_files(tmp_path / "raw")) == ["2026-01", "2026-02"]  # the core months only
    assert list(month_files(tmp_path / "raw", "extra")) == ["2026-01"]

    ds = load_hourly(tmp_path / "raw")
    jan, feb = ds.sel(time="2026-01-15"), ds.sel(time="2026-02-15")
    assert np.allclose(jan["ssrd"], 100.0) and np.allclose(jan["tp"], 0.5)
    assert ds["ssrd"].attrs["units"] == "W m-2" and ds["tp"].attrs["units"] == "mm"
    assert np.isnan(feb["ssrd"]).all()                    # no extra file for February yet
    assert "ssrd" not in load_hourly(tmp_path / "raw", extra=False)
    with pytest.raises(ValueError, match="group"):
        ERA5Ingestor(tmp_path / "raw", AREA, group="snow")
