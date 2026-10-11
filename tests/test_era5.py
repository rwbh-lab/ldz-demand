from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ldz_demand.data.ingest.era5 import ERA5Ingestor, gas_day_means, is_final, load_hourly, month_files

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


def hourly(start: str, hours: int) -> xr.Dataset:
    times = pd.date_range(start, periods=hours, freq="h")
    return xr.Dataset(
        {"t2m": (("time", "latitude"), np.arange(hours, dtype=float)[:, None].repeat(2, axis=1))},
        coords={"time": times, "latitude": [52.0, 51.75]},
    )


def test_gas_day_is_0500_local_and_drops_incomplete_days():
    # winter (GMT): gas day 2026-01-01 = 05:00 UTC 1 Jan .. 04:00 UTC 2 Jan
    daily = gas_day_means(hourly("2026-01-01 00:00", 72))
    assert list(pd.DatetimeIndex(daily["gas_day"].values).strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-02"]
    # hours 5..28 inclusive -> mean 16.5
    assert float(daily["t2m"].sel(gas_day="2026-01-01").isel(latitude=0)) == pytest.approx(16.5)


def test_gas_day_follows_bst():
    # summer (BST): gas day 2026-07-01 starts 04:00 UTC
    daily = gas_day_means(hourly("2026-07-01 04:00", 24))
    assert list(pd.DatetimeIndex(daily["gas_day"].values).strftime("%Y-%m-%d")) == ["2026-07-01"]


def test_gas_days_across_clock_changes_have_real_lengths():
    # spring: clocks go forward 2026-03-29 01:00 UTC, so gas day 2026-03-28 has 23 hours
    # (05:00 UTC 28th .. 03:00 UTC 29th); 05:00 BST on the 29th starts the next gas day
    spring = gas_day_means(hourly("2026-03-27 05:00", 24 + 23 + 24))
    assert list(pd.DatetimeIndex(spring["gas_day"].values).strftime("%Y-%m-%d")) == ["2026-03-27", "2026-03-28", "2026-03-29"]
    assert float(spring["t2m"].sel(gas_day="2026-03-28").isel(latitude=0)) == pytest.approx(np.mean(range(24, 47)))

    # autumn: clocks go back 2026-10-25 01:00 UTC, so gas day 2026-10-24 has 25 hours
    autumn = gas_day_means(hourly("2026-10-24 04:00", 25 + 24))
    assert list(pd.DatetimeIndex(autumn["gas_day"].values).strftime("%Y-%m-%d")) == ["2026-10-24", "2026-10-25"]

    # a gas day missing an hour is dropped
    gappy = hourly("2026-01-01 05:00", 48).drop_isel(time=[10])
    assert list(pd.DatetimeIndex(gas_day_means(gappy)["gas_day"].values).strftime("%Y-%m-%d")) == ["2026-01-02"]
