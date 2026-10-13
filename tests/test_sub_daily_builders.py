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
    assert len(out) == 2 * 15 * 2 * 2  # members x lead days x variants x variables (one LDZ)
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
    assert builder.build() == 2 * 15 * 2  # only the new run


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
