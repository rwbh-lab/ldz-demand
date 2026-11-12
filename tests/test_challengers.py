import numpy as np
import pandas as pd

from ldz_demand.models import calendar, climatology, control
from ldz_demand.models import experiment as ex
from ldz_demand.models.features import season_day

DAYS = pd.date_range("2021-10-01", "2024-09-30")


def _weather(seed=0):
    rng = np.random.default_rng(seed)
    doy = 2 * np.pi * DAYS.day_of_year.to_numpy() / 365.25
    return pd.DataFrame({"t2m": 10 - 6 * np.cos(doy) + rng.normal(0, 3, len(DAYS)),
                         "ws10": rng.uniform(1, 9, len(DAYS)), "ssrd": rng.uniform(0, 200, len(DAYS))}, index=DAYS)


def test_control_recovers_a_degree_day_line_and_calendar():
    f = _weather()
    cal = calendar.features(DAYS, "NT")
    f["target"] = 100 + 12 * np.clip(control.BASE - f["t2m"], 0, None) - 20 * cal["sun"] - 30 * cal["christmas"]
    train = np.ones(len(f), bool)
    fit = control.fit({"NT": (f, train)}, {"NT": np.linspace(0.2, 1, len(f))})["NT"]
    p = control.params(fit)
    assert fit.success and np.isclose(p["const"], 100) and np.isclose(p["hdd"], 12) and np.isclose(p["sun"], -20)
    assert np.allclose(control.predict(fit, f), f["target"])


def test_climatology_repeats_a_seasonal_pattern_and_weekday():
    f = _weather()
    sd = season_day(DAYS)
    f["target"] = 200 + 100 * np.cos(2 * np.pi * sd / 366) - 15 * (DAYS.day_of_week == 6)
    fit = climatology.fit({"NT": (f, np.ones(len(f), bool))})["NT"]
    err = climatology.predict(fit, f) - f["target"].to_numpy()
    assert fit.success and np.abs(err).max() < 3  # the ±7-day smoothing flattens the peak a little
    assert climatology.params(fit)["weekday_sun"] < climatology.params(fit)["weekday_mon"] - 12


def test_challenger_experiment_runs_every_family_on_the_same_days():
    raw = _weather()
    w = pd.concat({("sampled", "gas"): raw}, axis=1)
    w[("sampled", "gas", "t2m_heat")] = raw["t2m"] - 1
    target = 300 + 10 * np.clip(15.5 - raw["t2m"], 0, None)
    e = pd.DataFrame({"target": target, "target_repaired": target, "cwv_official": np.nan}, index=DAYS)
    frames = {"NT": pd.concat([w, e], axis=1)}
    models = [ex.FINAL, ex.CONTROL, ex.CLIMATOLOGY]
    pred, params = ex.run(frames, ["NT"], models, "forward")
    days = pred.groupby("input")["gas_day"].apply(frozenset)
    assert set(days.index) == {m.label for m in models} and len(set(days)) == 1
    s = ex.scores(pred).set_index(["ldz", "input"])
    assert s.loc[("NT", "control"), "rmse_all"] < 1e-6 < s.loc[("NT", "climatology"), "rmse_all"]
    assert params.groupby("input").size().to_dict() == {m.label: 1 for m in models}


def test_residual_tree_finds_a_planted_error():
    """Errors planted on cold-spell days in one LDZ: the tree splits on them, and the honest by-year test sees it."""
    from ldz_demand.models import diagnostics as dg

    raw = _weather(1)
    raw.loc[raw.index.month.isin([12, 1]), "t2m"] -= 6
    f = dg.candidates(raw.assign(tp=1.0, tmin=raw["t2m"] - 3, tmax=raw["t2m"] + 3), "NT")
    assert f.loc["2022-04-15", "school_holiday"] == 1 and f.loc["2022-10-24", "school_holiday"] == 1
    assert f.loc["2022-06-15", "school_holiday"] == 0 and f["cold_run"].max() >= 2
    rng = np.random.default_rng(0)
    table = f.assign(error_pct=rng.normal(0, 1, len(f)) + 4 * (f["cold_run"] >= 2),
                     held_out=np.where(DAYS < "2022-10-01", "2021/22", np.where(DAYS < "2023-10-01", "2022/23", "2023/24")),
                     ldz="NT").reset_index(names="gas_day")
    tree = dg.grow(table, depth=2)
    assert dg._x(table).columns[tree.tree_.feature[0]] in ("cold_run", "t", "t_lag1", "t_week", "tmin", "tmax")
    assert (dg.by_year(table, 2)["explained"] > 0.2).all()


def test_ebm_learns_a_monotone_pooled_curve_through_the_experiment(monkeypatch):
    """Two LDZs ten times apart in size, one shape: the pooled EBM fits both, and stays monotone in temperature."""
    from ldz_demand.models import ebm

    monkeypatch.setattr(ebm, "SETTINGS", dict(interactions=0, outer_bags=1, max_rounds=1000, random_state=0))

    raw = _weather(2)
    shape = 1 + 0.08 * np.clip(15.5 - raw["t2m"], 0, None) ** 1.3
    frames = {}
    for ldz, size in (("NT", 300.0), ("WS", 30.0)):
        w = pd.concat({("sampled", "gas"): raw}, axis=1)
        w[("sampled", "gas", "t2m_heat")] = raw["t2m"]
        e = pd.DataFrame({"target": size * shape, "cwv_official": np.nan}, index=DAYS)
        e["target_repaired"] = e["target"]
        frames[ldz] = pd.concat([w, e], axis=1)
    pred, params = ex.run(frames, ["NT", "WS"], [ex.EBM], "forward")
    rel = (pred["predicted"] - pred["actual"]).abs() / pred["actual"]
    assert rel.mean() < 0.02 and set(params["ldz"]) == {"NT", "WS"}
    fits = ebm.fit({ldz: (ex._prepared(f, "sampled_gas", "target_repaired", "t2m_heat")[0],
                          np.ones(len(DAYS), bool)) for ldz, f in frames.items()})
    ramp = pd.DataFrame({"t2m": np.linspace(-5, 20, 30), "ws10": 5.0, "ssrd": 50.0},
                        index=pd.date_range("2023-01-09", periods=30))
    ramp["t2m"] = ramp["t2m"].to_numpy()
    p = ebm.predict(fits["NT"], ramp)[2:]
    assert np.isclose(fits["NT"].scale / fits["WS"].scale, 10, rtol=0.01)
    assert ebm.terms(fits["NT"])["term"].iloc[0] in ("t", "t_lag1", "t_lag2")
    assert len(p) and p[0] > p[-1]


def test_bridge_days():
    days = pd.to_datetime(["2024-03-28", "2024-04-02", "2024-12-23", "2024-12-24", "2024-12-27", "2025-01-15",
                           "2025-12-31", "2026-01-02"])
    assert calendar.bridge(days, "NT").tolist() == [True, True, False, True, True, False, True, True]
    assert not calendar.bridge(pd.to_datetime(["2026-01-02"]), "SC")[0]  # a bank holiday in Scotland
    assert "bridge" not in calendar.features(days, "NT") and "bridge" in calendar.features(days, "NT", ("bridge",))


def test_cwv_extras_add_their_terms_and_recover_them():
    from ldz_demand.models import cwv, demand

    from tests.test_models import DAYS as MODEL_DAYS, synthetic

    p = cwv.fixed_values("NT", "fitted", True)
    f = synthetic("NT", p)
    cal = calendar.features(MODEL_DAYS, "NT", ("bridge",))
    x = demand.composite(f["t2m"].to_numpy(), f["ws10"].to_numpy(), f["ssrd"].to_numpy(), p)
    f["target"] += -6 * cal["bridge"] + 0.5 * (cal["sat"] + cal["sun"]) * x
    fit = demand.fit_weather(f, np.ones(len(f), bool), "NT", extras=("bridge", "weekend_cwv"))
    coef = dict(zip(fit.columns, fit.coef))
    assert fit.extras == ("bridge", "weekend_cwv") and abs(coef["bridge"] + 6) < 1.5 and coef["weekend_cwv"] != 0
    plain = demand.fit_weather(f, np.ones(len(f), bool), "NT")
    assert "bridge" not in plain.columns and len(demand.predict(fit, f)) == len(f)
    def rmse(m):
        return np.sqrt(np.mean((demand.predict(m, f) - f["target"]) ** 2))

    assert rmse(fit) < rmse(plain)



def test_consistency_flags_a_group_that_leans_the_same_way_every_year():
    from ldz_demand.models import diagnostics as dg

    rng = np.random.default_rng(0)
    n = 3000
    t = pd.DataFrame({"tmax": rng.uniform(-2, 15, n), "weekday": rng.integers(0, 7, n), "bridge": rng.random(n) < 0.05,
                      "season_day": rng.integers(0, 366, n), "cold_run": rng.integers(0, 5, n),
                      "school_holiday": rng.random(n) < 0.1, "held_out": rng.choice(["a", "b", "c"], n), "ldz": "NT"})
    t["error_pct"] = rng.normal(0, 0.3, n) + 3 * t["bridge"] + np.where(t["held_out"] == "b", 2, -2) * (t["cold_run"] >= 3)
    c = dg.consistency(t).groupby("group")["consistent"].first()
    assert c["bridge day"] and not c["cold spell (3+ days below 3 °C)"]
