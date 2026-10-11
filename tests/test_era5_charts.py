import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ldz_demand.charts import era5 as ch
from ldz_demand.charts import style
from ldz_demand.data.build.gas_day import gas_day_slice


def hourly_grid(start="2026-01-01 00:00", hours=48):
    times = pd.date_range(start, periods=hours, freq="h")
    lat = np.arange(55.75, 53.75, -0.25)   # 8 rows, descending like ERA5
    lon = np.arange(-2.0, 0.0, 0.25)       # 8 columns
    shape = (hours, len(lat), len(lon))
    return xr.Dataset({"t2m": (("time", "latitude", "longitude"), np.full(shape, 3.0)),
                       "ws10": (("time", "latitude", "longitude"), np.full(shape, 6.0))},
                      coords={"time": times, "latitude": lat, "longitude": lon})


def test_gas_day_slice_takes_local_0500_to_0400():
    day = gas_day_slice(hourly_grid(), "2026-01-01")
    local = pd.DatetimeIndex(day["local_time"].values)
    assert day.sizes["time"] == 24
    assert local[0] == pd.Timestamp("2026-01-01 05:00") and local[-1] == pd.Timestamp("2026-01-02 04:00")


def test_coarsen_to_one_degree():
    grid = ch.coarsen(hourly_grid(), 1.0)
    assert (grid.sizes["latitude"], grid.sizes["longitude"]) == (2, 2)
    assert float(grid["t2m"].mean()) == pytest.approx(3.0)


def test_grid_map_has_a_frame_per_hour_and_clockwise_cells():
    style.use()
    day = gas_day_slice(hourly_grid(), "2026-01-01")
    fig = ch.grid_map(day, "t2m", 1.0)
    assert len(fig.frames) == 24
    assert fig.frames[0].name == "05:00"
    ring = fig.data[0].geojson["features"][0]["geometry"]["coordinates"][0]
    signed_area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:]))
    assert signed_area < 0  # clockwise; anticlockwise rings fill the whole globe in Plotly


def test_sample_days_are_unique_dates():
    days = [d.day for d in ch.SAMPLE_DAYS]
    assert len(days) == len(set(days))
    pd.to_datetime(days)
