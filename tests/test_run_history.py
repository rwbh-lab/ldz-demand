import numpy as np
import pandas as pd
from scipy.special import ndtri

from ldz_demand.charts import run_history as rh
from ldz_demand.charts import style


def _runs(n_runs=5, horizon=4):
    """Normal forecasts, mean 1000 and sigma 50 + 10 per lead day, for runs on consecutive days."""
    rows = []
    for r in range(n_runs):
        run = pd.Timestamp("2026-11-01") + pd.Timedelta(days=r)
        for lead in range(horizon):
            sigma = 50 + 10 * lead
            rows.append({"run_date": run, "ldz": "GB", "gas_day": run + pd.Timedelta(days=lead), "lead_days": lead,
                         **dict(zip(rh.COLS, 1000 + sigma * ndtri(rh.LEVELS))),
                         "weather_p10": 950.0, "weather_p90": 1050.0})
    return pd.DataFrame(rows)


def _actual(runs):
    days = sorted(runs["gas_day"].unique())[:5]
    return pd.DataFrame({"ldz": "GB", "gas_day": days, "actual": 1010.0, "provisional": False})


def test_cdf_is_exact_for_a_normal_forecast():
    q = 1000 + 50 * ndtri(rh.LEVELS)
    x = np.array([880.0, 1000.0, 1100.0])  # inside and beyond the stored points
    assert np.allclose(rh.cdf(x, q), [0.0082, 0.5, 0.9772], atol=1e-3)


def test_blend_of_identical_runs_is_that_run_and_far_days_use_the_newest():
    runs = _runs()
    b = rh.blend(runs, "GB", runs["run_date"].max(), "decay")
    assert len(b) == 4 and b["runs"].tolist() == [4, 3, 2, 1]
    first = b.iloc[-1]  # one run only
    assert np.isclose(first["p50"], first["single_p50"]) and first["newest_share"] == 1.0


def test_blend_score_and_all_views_build():
    style.use()
    runs, actual = _runs(), None
    actual = _actual(runs)
    day = rh.default_target_day(runs, actual, "GB")
    assert day in set(actual["gas_day"])
    for how in rh.WEIGHTINGS.values():
        s = rh.blend_score(runs, actual, "GB", how)
        assert s["days"] > 0 and 0 <= s["blend_cover"] <= 100
    rh.ridgeline(runs, actual, "GB", day)
    rh.blend_chart(rh.blend(runs, "GB", runs["run_date"].max()), actual, "GB", runs["run_date"].max(), "Equal")
    for m in rh.HEATMAP_MEASURES.values():
        for r in rh.HEATMAP_ROWS.values():
            rh.run_heatmap(runs, actual, "GB", m, r)
    e = rh.error_by_lead(runs, actual, "GB")
    assert np.isclose(e["mean"].iloc[0], -0.99, atol=0.01)  # medians of 1000 against actuals of 1010
    rh.exceedance(runs, actual, "GB", rh.default_threshold(runs, "GB"))


def test_scores_use_closed_out_days_only():
    runs = _runs()
    actual = _actual(runs)
    actual.loc[actual.index[-2:], "provisional"] = True  # two days still provisional
    s = rh.blend_score(runs, actual, "GB", "equal")
    w = rh._with_error(runs, actual, "GB")
    closed = set(actual.loc[~actual["provisional"], "gas_day"])
    assert s["days"] == runs[runs["gas_day"].isin(closed)].shape[0]
    assert set(w.dropna(subset=["error"])["gas_day"]) == closed
