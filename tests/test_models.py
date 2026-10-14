import numpy as np
import pandas as pd
import pytest

from ldz_demand.models import calendar, cwv, demand

DAYS = pd.date_range("2021-10-01", "2025-09-30")


def synthetic(ldz: str, p: cwv.CWVParams, seasonal="none", shape=None, seed=0, breaks=(), shift=(0.0, 0.0)):
    """A frame of weather and a target made from the model itself, plus small noise."""
    rng = np.random.default_rng(seed)
    doy = 2 * np.pi * DAYS.dayofyear.to_numpy() / 365.25
    t = 10 - 6 * np.cos(doy) + rng.normal(0, 3, len(DAYS))
    w = np.abs(rng.normal(5, 2, len(DAYS)))
    sr = np.clip(120 - 90 * np.cos(doy) + rng.normal(0, 30, len(DAYS)), 0, None)
    frame = pd.DataFrame({"t2m": t, "ws10": w, "ssrd": sr}, index=DAYS)
    s, g = demand._seasonal(t, DAYS, p, seasonal, shape)
    x = demand.composite(t, w, sr, p, s, g)
    cal = calendar.features(DAYS, ldz)
    y = 300 - 15 * x - 5 * cal["sat"] - 5 * cal["sun"] - 8 * cal["christmas"]
    for b in breaks:
        post = DAYS >= b
        y = y + post * (shift[0] + shift[1] * x)
    frame["target"] = y + rng.normal(0, 1, len(DAYS))
    return frame


def test_regimes_count_the_breaks_passed():
    r = demand.regimes(pd.to_datetime(["2022-09-30", "2022-10-01", "2025-10-01"]),
                       (demand.BEHAVIOUR_BREAK, demand.BREAK_DAY))
    assert list(r) == [0, 1, 2]


def test_calendar_features():
    f = calendar.features(pd.to_datetime(["2025-12-25", "2025-12-27", "2025-08-25", "2025-08-04"]), "NT")
    assert f.loc["2025-12-25", "bank_holiday"] == 1 and f.loc["2025-12-27", "christmas"] == 1
    assert f.loc["2025-12-27", "sat"] == 1
    assert f.loc["2025-08-25", "bank_holiday"] == 1                     # England's late summer holiday
    sc = calendar.features(pd.to_datetime(["2025-08-04", "2025-08-25"]), "SC")
    assert list(sc["bank_holiday"]) == [1, 0]                            # Scotland's is the first Monday


def test_params_round_trip_with_seasonal_names():
    p = cwv.start("NT")
    for seasonal in cwv.SEASONAL:
        names = cwv.free_names(seasonal)
        lo, hi = cwv.bounds("NT", names)
        assert len(lo) == len(hi) == len(names) and (lo < hi).all()
        assert cwv.CWVParams.from_vector(p.vector(names), names).vector(names) == pytest.approx(p.vector(names))


@pytest.mark.parametrize("seasonal", ["none", "slow"])
def test_weather_fit_recovers_a_known_model(seasonal):
    true = cwv.CWVParams(y=0.5, I2=0.03, W0=3.0, T0=15.0, S0=0.01, V0=3.0, I3=0.1, V1=14.0, dV=4.0, q=0.4,
                         I1=0.75, ys=0.93)
    frame = synthetic("NT", true, seasonal)
    fit = demand.fit_weather(frame, np.ones(len(frame), bool), "NT", seasonal)
    assert fit.success
    resid = demand.predict(fit, frame) - frame["target"].to_numpy()
    assert np.sqrt(np.mean(resid ** 2)) < 1.5                            # noise is 1
    assert fit.params.y == pytest.approx(0.5, abs=0.05)
    if seasonal == "slow":
        assert fit.params.I1 == pytest.approx(0.75, abs=0.1)


def test_joint_calendar_fit_shares_the_shape_and_recovers_it():
    shape = np.array([0.3, 0.05, -0.1])
    frames = {ldz: synthetic(ldz, cwv.CWVParams(y=0.45, I2=0.02, W0=2.0, T0=15.0, S0=0.0, V0=3.0, I3=0.0, V1=14.0,
                                                dV=4.0, q=0.4, Sc=sc), "calendar", shape, seed=i)
              for i, (ldz, sc) in enumerate((("NT", -2.5), ("SO", -1.5)))}
    fits = demand.fit_joint({k: (f, np.ones(len(f), bool)) for k, f in frames.items()}, "calendar")
    assert np.array_equal(fits["NT"].shape, fits["SO"].shape)
    assert fits["NT"].shape == pytest.approx(shape, abs=0.1)
    assert fits["NT"].params.Sc == pytest.approx(-2.5, abs=0.3) and fits["SO"].params.Sc == pytest.approx(-1.5, abs=0.3)


def test_breaks_shift_level_and_slope():
    p = cwv.CWVParams(y=0.5, I2=0.0, W0=0.0, T0=15.0, S0=0.0, V0=-5.0, I3=0.0, V1=30.0, dV=1.0, q=0.5)
    frame = synthetic("NT", p, breaks=(demand.BEHAVIOUR_BREAK,), shift=(-20.0, 1.5))
    fit = demand.fit_weather(frame, np.ones(len(frame), bool), "NT", breaks=(demand.BEHAVIOUR_BREAK,))
    coef = dict(zip(fit.columns, fit.coef))
    assert coef["intercept_after_2022-10"] == pytest.approx(-20.0, abs=2.0)
    assert coef["cwv_after_2022-10"] == pytest.approx(1.5, abs=0.2)


def test_gas_day_temperature_profiles_and_steps():
    from ldz_demand.models import averaging

    times = pd.date_range("2025-01-06 05:00", periods=24 * 3, freq="h")  # GMT: gas days start 05:00 UTC
    hourly = pd.Series(np.where(times.hour.isin(range(6, 9)), 10.0, 0.0), index=times)  # warm mornings only
    flat = averaging.gas_day_temperature(hourly, "flat")
    peaks = averaging.gas_day_temperature(hourly, "peaks")
    assert flat.iloc[0] == pytest.approx(30 / 24)
    assert peaks.iloc[0] > flat.iloc[0]                                     # the morning peak counts double
    steady = pd.Series(5.0, index=times)
    assert averaging.gas_day_temperature(steady, "peaks", step_hours=3).iloc[0] == pytest.approx(5.0)
    assert len(averaging.gas_day_temperature(hourly.iloc[:-5])) == 2        # an incomplete last day is dropped


def test_final_fit_saves_and_loads_to_the_same_predictions(tmp_path):
    from ldz_demand.models import fit as final

    shape = np.array([0.3, 0.05, -0.1])
    frames = {ldz: synthetic(ldz, cwv.CWVParams(y=0.45, I2=0.02, W0=2.0, T0=15.0, S0=0.0, V0=3.0, I3=0.1, V1=14.0,
                                                dV=4.0, q=0.4, Sc=sc), "calendar", shape, seed=i)
              for i, (ldz, sc) in enumerate((("NT", -2.5), ("SO", -1.5)))}
    fits = demand.fit_joint({k: (f, np.ones(len(f), bool)) for k, f in frames.items()}, "calendar")
    loaded = final.load(final.save(fits, out_dir=tmp_path))
    assert set(loaded) == set(fits)
    for ldz, f in fits.items():
        assert demand.predict(loaded[ldz], frames[ldz]) == pytest.approx(demand.predict(f, frames[ldz]), rel=1e-6)
    assert (tmp_path / final.OUTPUT).read_text().startswith("# Derived by ldz-demand")
