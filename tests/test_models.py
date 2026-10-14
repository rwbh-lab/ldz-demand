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


def test_forecast_intervals_add_model_error_and_keep_ldzs_consistent():
    from ldz_demand.models import forecast

    days = pd.date_range("2026-10-13", periods=3)
    rng = np.random.default_rng(0)
    rows = [{"ldz": ldz, "member": m, "gas_day": d, "demand": base * (1 + 0.01 * rng.normal()), "run_date": days[0]}
            for ldz, base in (("NT", 100.0), ("SO", 50.0)) for m in range(1, 51) for d in days]
    fc = pd.DataFrame(rows)
    hist = pd.date_range("2024-09-01", "2025-11-30")
    shock = rng.normal(0, 0.06, len(hist))                       # errors shared across LDZs (correlated)
    pool = pd.DataFrame({"NT": shock + rng.normal(0, 0.01, len(hist)), "SO": shock + rng.normal(0, 0.01, len(hist))},
                        index=hist)
    st = forecast.summary(forecast.statistics(fc, pool, seed=1))
    for ldz in ("NT", "SO", "GB"):
        r = st[st["ldz"] == ldz].iloc[0]
        assert r["p10"] < r["weather_p10"] and r["p90"] > r["weather_p90"]   # model error widens the interval
        assert r["p05"] < r["p25"] < r["p50"] < r["p75"] < r["p95"]
    gb, nt = st[st["ldz"] == "GB"].iloc[0], st[st["ldz"] == "NT"].iloc[0]
    assert gb["p50"] == pytest.approx(150, rel=0.02)                  # centred errors: the median stays put
    assert (gb["p90"] - gb["p10"]) / gb["p50"] == pytest.approx((nt["p90"] - nt["p10"]) / nt["p50"], rel=0.2)  # correlated


class _StubStore:
    """read() returns canned frames per dataset name (empty with the schema otherwise)."""

    def __init__(self, frames):
        self.frames = frames

    def read(self, dataset, start=None, end=None, **filters):
        df = self.frames.get(dataset.name, pd.DataFrame(columns=list(dataset.columns)))
        for k, v in filters.items():
            df = df[df[k].isin(v if isinstance(v, (list, tuple, set)) else [v])]
        return df


def test_forecast_warm_up_uses_only_era5_available_at_issue():
    from ldz_demand.models import forecast

    run = pd.Timestamp("2026-10-13")
    days = pd.date_range("2026-08-01", run - pd.Timedelta(days=1))
    inputs = {"NT": pd.DataFrame({"t2m": np.arange(len(days), dtype=float), "ws10": 5.0, "ssrd": 100.0}, index=days)}
    past, bridged = forecast.history(run, inputs, _StubStore({}), ldzs=["NT"])
    cut = run - pd.Timedelta(days=forecast.ERA5_LAG_DAYS)
    t = past["NT"]["t2m"]
    assert t.loc[:cut].equals(inputs["NT"]["t2m"].reindex(t.loc[:cut].index))   # ERA5 up to the cut
    assert (t.loc[cut + pd.Timedelta(days=1):] == t.loc[cut]).all()            # after it: not the later ERA5
    assert bridged == forecast.ERA5_LAG_DAYS - 1


def test_missing_runs_needs_inputs_and_no_stored_forecast():
    from ldz_demand.models import forecast

    def ens(run, variables):
        return [{"run_date": pd.Timestamp(run), "ldz": "NT", "member": 1, "lead_days": 0, "membership": "sampled",
                 "weighting": "gas", "variable": v, "value": 1.0} for v in variables]
    e = pd.DataFrame(ens("2026-10-12", ["t2m_heat"]) + ens("2026-10-13", ["t2m_heat", "ssrd"])
                     + ens("2026-10-14", ["t2m_heat", "ssrd"]))
    stored = pd.DataFrame([{"run_date": pd.Timestamp("2026-10-13"), "ldz": "GB", "statistic": "p50", "lead_days": 0}])
    store = _StubStore({"ens_ldz_daily": e, "demand_forecast_daily": stored})
    assert forecast.missing_runs(store) == ["2026-10-14"]   # 12th has no solar; 13th already forecast
