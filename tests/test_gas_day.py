import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ldz_demand.data.build.gas_day import gas_day_means


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


def test_heating_hours_mean_matches_experiment_5():
    """The builders' heating-hours mean is the one experiment 5 tested (models.averaging)."""
    import xarray as xr

    from ldz_demand.data.build import gas_day as gd
    from ldz_demand.models import averaging

    times = pd.date_range("2026-03-27 00:00", "2026-04-01 00:00", freq="h")  # spans the clock change (29 Mar)
    rng = np.random.default_rng(1)
    temp = 8 + 4 * np.sin(2 * np.pi * (times.hour.to_numpy() - 9) / 24) + rng.normal(0, 0.5, len(times))
    expected = averaging.gas_day_temperature(pd.Series(temp, index=times), "peaks")
    # daily builder: gas_day_stats over hourly fields
    ds = xr.Dataset({"t2m": ("time", temp)}, coords={"time": times})
    got = gd.gas_day_stats(ds)["t2m_heat"].to_series()
    common = expected.index.intersection(got.index)
    assert len(common) >= 4 and np.allclose(got.loc[common], expected.loc[common])
    # ensemble: from 3-hourly steps, as the thinned hourly series in experiment 5
    steps = times[times.hour % 3 == 0]
    means, covered = gd.gas_day_time_mean(temp[times.hour % 3 == 0], steps, common, "heating")
    thinned = averaging.gas_day_temperature(pd.Series(temp, index=times), "peaks", step_hours=3)
    assert np.allclose(means, thinned.loc[common]) and (covered >= 23).all()


def test_hour_weights():
    from ldz_demand.data.build import gas_day as gd

    w = gd.hour_weights(np.arange(24))
    assert w[7] == 2 and w[18] == 2 and w[2] == 0.5 and w[12] == 1 and w[23] == 0.5 and w[5] == 1
    assert (gd.hour_weights(np.arange(24), "flat") == 1).all()
