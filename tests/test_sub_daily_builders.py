from datetime import datetime

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ldz_demand.data.build.ens_ldz_daily import EnsLdzDailyBuilder, ens_ldz_daily
from ldz_demand.data.build.gas_day import gas_day_bounds, gas_day_time_mean, time_weights
from ldz_demand.data.build.weather_ldz_hourly import ldz_hourly
from ldz_demand.data.datasets import ENS_LDZ_DAILY
from ldz_demand.data.ingest.ecmwf_ens import STEPS
from ldz_demand.data.store import CsvCacheStore
from ldz_demand.geo import grid_weights as gw

LAT, LON = np.array([52.0, 51.75]), np.array([-1.0, -0.75])
RUN = datetime(2026, 10, 13)


def weights(variants=(("sampled", "gas"), ("station", "point"))):
    rows = [dict(membership=m, weighting=w, variable=v, ldz="NT", lat=la, lon=lo, weight=0.25)
            for m, w in variants for v in ("t2m", "ws10") for la in LAT for lo in LON]
    return pd.DataFrame(rows)


def test_gas_day_bounds_follow_uk_clock_changes():
    start, end = gas_day_bounds(pd.DatetimeIndex(["2026-01-15", "2026-07-15", "2026-10-24"]))
    assert list(start.hour) == [5, 4, 4] and list(end.hour) == [5, 4, 5]  # the 24 Oct gas day is 25 hours


def test_time_weights_give_each_sample_the_time_it_stands_for():
    day = pd.DatetimeIndex(["2026-01-15"])  # 05:00-05:00 UTC
    three = pd.date_range("2026-01-15 00:00", "2026-01-16 06:00", freq="3h")
    w = time_weights(three, day)[0]
    # linear between samples: 03:00 carries 03-06 falling (1/6 h of it after 05:00), 06:00 rising and falling ...
    assert np.allclose(w, [0, 1 / 6, 1.5 + 5 / 6, 3, 3, 3, 3, 3, 3, 1.5 + 4 / 3, 2 / 3])
    assert w.sum() == pytest.approx(24)
    # uneven spacing (3-hourly then 6-hourly): weights still add up to the hours covered
    uneven = pd.DatetimeIndex(["2026-01-15 03:00", "2026-01-15 06:00", "2026-01-15 09:00", "2026-01-15 15:00",
                               "2026-01-15 21:00", "2026-01-16 03:00", "2026-01-16 09:00"])
    w = time_weights(uneven, day)[0]
    assert w.sum() == pytest.approx(24) and w[3] == pytest.approx(6) and w[2] == pytest.approx(1.5 + 3)


def test_gas_day_time_mean_and_coverage_on_a_real_step_list():
    times = pd.Timestamp(RUN) + pd.to_timedelta(STEPS, unit="h")
    days = pd.date_range(RUN, periods=15)
    hours = ((times - times[0]) / pd.Timedelta(hours=1)).to_numpy()
    means, covered = gas_day_time_mean(np.vstack([np.full(len(times), 7.0), hours]), times, days)
    assert np.allclose(means[0], 7.0)                       # a constant stays constant
    assert covered.tolist()[:11] == [24] * 11 and covered[11] == 25 and covered[14] == 22  # clocks go back 25 Oct
    start, end = gas_day_bounds(days)
    mid = (((start - times[0]) + (end - start) / 2) / pd.Timedelta(hours=1)).to_numpy()
    assert np.allclose(means[1][:14], mid[:14])              # a straight line averages to the middle, even on uneven days
    with pytest.raises(ValueError, match="averaging method"):
        gas_day_time_mean(means, times, days, method="evening")


def ens_run(run=RUN, t2m_kelvin=280.15, members=(1, 2)):
    times = pd.Timestamp(run) + pd.to_timedelta(STEPS, unit="h")
    shape = (len(times), len(members), len(LAT), len(LON))
    base = np.broadcast_to(np.array(members, float)[None, :, None, None], shape)  # member n is n degrees warmer
    ds = xr.Dataset({"t2m": (("time", "number", "latitude", "longitude"), t2m_kelvin - 273.15 + base),
                     "u10": (("time", "number", "latitude", "longitude"), np.full(shape, 3.0)),
                     "v10": (("time", "number", "latitude", "longitude"), np.full(shape, 4.0))},
                    coords={"time": times, "number": list(members), "latitude": LAT, "longitude": LON})
    ds["ws10"] = np.hypot(ds["u10"], ds["v10"])
    return ds


def test_ens_ldz_daily_rows_per_member_lead_and_variant():
    out = ens_ldz_daily(ens_run(), weights(), RUN)
    assert len(out) == 2 * 15 * 2 * 3  # members x lead days x variants x variables (t2m, t2m_heat, ws10; one LDZ)
    assert sorted(out["lead_days"].unique()) == list(range(15))
    t = out[(out["variable"] == "t2m") & (out["membership"] == "sampled")].set_index(["member", "lead_days"])
    assert t.loc[(1, 3), "value"] == pytest.approx(8.0) and t.loc[(2, 3), "value"] == pytest.approx(9.0)
    assert t.loc[(1, 14), "coverage_h"] == pytest.approx(22)
    assert np.allclose(out.loc[out["variable"] == "ws10", "value"], 5.0)
    assert set(out["method"]) == {"flat"} and set(out["run_hour"]) == {0}


def test_ens_builder_builds_new_runs_only(tmp_path, monkeypatch):
    from ldz_demand.data.build import ens_ldz_daily as mod

    runs = {RUN: None, datetime(2026, 10, 12): None}
    monkeypatch.setattr(mod, "archived_runs", lambda raw: runs)
    monkeypatch.setattr(mod, "load_run", lambda raw, run: ens_run(run))
    store = CsvCacheStore(tmp_path / "cache")
    builder = EnsLdzDailyBuilder(store, tmp_path, weights=weights([("sampled", "gas")]))
    builder.build()
    assert set(store.read(ENS_LDZ_DAILY)["run_date"].dt.date) == {RUN.date(), datetime(2026, 10, 12).date()}
    assert builder.build() == 0
    runs[datetime(2026, 10, 14)] = None
    assert builder.build() == 2 * 15 * 3  # only the new run


def test_ldz_hourly_is_the_weighted_mean_each_hour():
    times = pd.date_range("2026-01-01", periods=3, freq="h")
    t2m = np.stack([np.array([[10.0, 12.0], [14.0, 16.0]]) + h for h in range(3)])
    ds = xr.Dataset({"t2m": (("time", "latitude", "longitude"), t2m),
                     "ws10": (("time", "latitude", "longitude"), np.full(t2m.shape, 5.0))},
                    coords={"time": times, "latitude": LAT, "longitude": LON})
    out = ldz_hourly(ds, weights([("sampled", "gas")])).set_index(["variable", "time"])["value"]
    assert out[("t2m", times[0])] == pytest.approx(13.0) and out[("t2m", times[2])] == pytest.approx(15.0)


def test_detail_variants_are_in_the_committed_weights():
    sel = gw.select(gw.load(), gw.detail_variants())
    assert set(map(tuple, sel[["membership", "weighting"]].drop_duplicates().to_numpy())) == {("sampled", "gas"), ("station", "point")}
    with pytest.raises(ValueError, match="not in the cell weights"):
        gw.select(gw.load(), [("sampled", "population")])


# --- extra variables: solar radiation, precipitation, temperature extremes -----------------------

def test_gas_day_stats_mean_min_max_and_sum_over_complete_days():
    from ldz_demand.data.build.gas_day import gas_day_stats

    times = pd.date_range("2026-01-14 00:00", "2026-01-17 00:00", freq="h")
    hour = np.arange(len(times), dtype=float)
    ds = xr.Dataset({"t2m": ("time", np.sin(hour / 24 * 2 * np.pi) * 5),
                     "ws10": ("time", np.full(len(times), 4.0)),
                     "ssrd": ("time", np.full(len(times), 100.0)),
                     "tp": ("time", np.full(len(times), 0.5))}, coords={"time": times})
    out = gas_day_stats(ds).sel(gas_day=["2026-01-14", "2026-01-15"])
    assert np.allclose(out["tp"], 12.0) and np.allclose(out["ssrd"], 100.0) and np.allclose(out["ws10"], 4.0)
    assert (out["tmin"] < out["t2m"]).all() and (out["t2m"] < out["tmax"]).all()
    assert np.allclose(out["tmax"] - out["tmin"], 10.0, atol=0.2)
    # one missing hour of precipitation: that day's total is missing, not partial
    gap = ds.copy(deep=True)
    gap["tp"][30] = np.nan
    assert np.isnan(gas_day_stats(gap)["tp"].sel(gas_day="2026-01-15"))


def test_interval_statistics_for_period_values():
    from ldz_demand.data.build.gas_day import gas_day_interval_stat, interval_weights

    day = pd.DatetimeIndex(["2026-01-15"])                  # 05:00-05:00 UTC
    times = pd.date_range("2026-01-15 00:00", "2026-01-16 09:00", freq="3h")
    assert interval_weights(times, day)[0].tolist() == [0, 0, 1, 3, 3, 3, 3, 3, 3, 3, 2, 0]
    rain = np.full((1, len(times)), 1.5)                    # 1.5 mm per 3-hour period = 0.5 mm an hour
    total, covered = gas_day_interval_stat(rain, times, day, "sum")
    assert total[0, 0] == pytest.approx(12.0) and covered[0] == pytest.approx(24)
    v = np.arange(len(times), dtype=float)[None, :]
    assert gas_day_interval_stat(v, times, day, "min")[0][0, 0] == 3   # periods at least half inside
    assert gas_day_interval_stat(v, times, day, "max")[0][0, 0] == 10


def ens_run_full(run=RUN, members=(1, 2)):
    """A run with every variable: 100 W m-2, 0.5 mm an hour, extremes 2 degC either side of t2m."""
    ds = ens_run(run, members=members)
    hours = ((ds["time"] - ds["time"][0]) / np.timedelta64(1, "h")).values
    gaps = np.diff(hours, prepend=0)
    base = xr.ones_like(ds["t2m"])
    ds["ssrd"] = base * 100.0
    ds["tp"] = base * xr.DataArray(0.5 * gaps, dims="time", coords={"time": ds["time"]})
    ds["tmin"], ds["tmax"] = ds["t2m"] - 2, ds["t2m"] + 2
    for v in ("ssrd", "tp", "tmin", "tmax"):
        ds[v][0] = np.nan                                    # no period at the first step
    return ds


def test_ens_ldz_daily_extra_variables():
    out = ens_ldz_daily(ens_run_full(), weights([("sampled", "gas")]), RUN)
    v = out[out["member"] == 1].set_index(["variable", "lead_days"])
    hours = v.loc["tp", "coverage_h"].loc[0:13]                 # 24, and 25 on the clock-change day
    assert np.allclose(v.loc["tp", "value"].loc[0:13], 0.5 * hours)  # 3- and 6-hourly days alike
    assert np.allclose(v.loc["ssrd", "value"], 100.0)
    assert v.loc[("tmin", 3), "value"] == pytest.approx(6.0) and v.loc[("tmax", 3), "value"] == pytest.approx(10.0)
    assert v.loc[("tp", 14), "coverage_h"] < 24                  # lead day 14 is partly covered
    # a run archived before the extra variables still builds, with temperature and wind only
    old = ens_ldz_daily(ens_run(), weights([("sampled", "gas")]), RUN)
    assert set(old["variable"]) == {"t2m", "t2m_heat", "ws10"}


def test_weather_ldz_daily_includes_extra_variables_where_archived(tmp_path):
    from ldz_demand.data.build.weather_ldz_daily import WeatherLdzDailyBuilder
    from ldz_demand.data.datasets import WEATHER_LDZ_DAILY

    raw = tmp_path / "raw" / "era5" / "2026"
    raw.mkdir(parents=True)
    for month, extra in (("2026-01", True), ("2026-02", False)):
        times = pd.date_range(f"{month}-01", pd.Period(month, freq="M").end_time.floor("h"), freq="h")
        shape = (len(times), len(LAT), len(LON))
        dims = ("valid_time", "latitude", "longitude")
        coords = {"valid_time": times, "latitude": LAT, "longitude": LON}
        xr.Dataset({"t2m": (dims, np.full(shape, 278.15)), "u10": (dims, np.full(shape, 3.0)),
                    "v10": (dims, np.full(shape, 4.0))}, coords=coords).to_netcdf(raw / f"era5_gb_{month}.nc")
        if extra:
            xr.Dataset({"ssrd": (dims, np.full(shape, 360000.0)), "tp": (dims, np.full(shape, 0.0005))},
                       coords=coords).to_netcdf(raw / f"era5x_gb_{month}.nc")
    store = CsvCacheStore(tmp_path / "cache")
    WeatherLdzDailyBuilder(store, tmp_path / "raw", weights=weights([("sampled", "gas")])).build()
    out = store.read(WEATHER_LDZ_DAILY).set_index(["variable", "gas_day"])["value"]
    assert out[("tp", pd.Timestamp("2026-01-15"))] == pytest.approx(12.0)
    assert out[("ssrd", pd.Timestamp("2026-01-15"))] == pytest.approx(100.0)
    assert out[("tmin", pd.Timestamp("2026-02-15"))] == pytest.approx(5.0)
    assert ("tp", pd.Timestamp("2026-02-15")) not in out.index   # February has no extra file
    assert ("tp", pd.Timestamp("2026-01-31")) not in out.index   # its last hours fall in February
