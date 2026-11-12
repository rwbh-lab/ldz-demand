import sys
import types

import numpy as np
import pandas as pd
import pytest

from ldz_demand.models import experiment as ex
from ldz_demand.models import features as ft


def _frame(days):
    rng = np.random.default_rng(0)
    return pd.DataFrame({"t2m": rng.normal(8, 4, len(days)), "ws10": rng.uniform(1, 9, len(days)),
                         "ssrd": rng.uniform(0, 200, len(days))}, index=days)


def test_season_day_counts_from_1_october():
    days = pd.to_datetime(["2024-10-01", "2024-12-25", "2025-09-30", "2025-10-01"])
    assert list(ft.season_day(days)) == [0, 85, 364, 0]


def test_features_lag_by_row_and_use_the_calendar():
    days = pd.date_range("2024-12-23", periods=5)
    frame = _frame(days)
    frame.loc[days[1], "ssrd"] = np.nan
    f = ft.features(frame, "NT")
    assert list(f.columns) == list(ft.FEATURES)
    assert np.isnan(f["t_lag1"].iloc[0]) and np.isnan(f["t_lag2"].iloc[1])
    assert f["t_lag1"].iloc[2] == frame["t2m"].iloc[1] and f["t_lag2"].iloc[4] == frame["t2m"].iloc[2]
    assert f["christmas"].tolist() == [0, 1, 1, 1, 1] and f["bank_holiday"].tolist() == [0, 0, 1, 1, 0]
    assert f["weekday"].iloc[0] == 0 and not f["ssrd"].isna().any()
    assert set(ft.MONOTONE) <= set(ft.FEATURES) and set(ft.CATEGORICAL) <= set(ft.FEATURES)


def test_features_refuse_a_gap_in_the_days():
    with pytest.raises(ValueError, match="consecutive"):
        ft.features(_frame(pd.to_datetime(["2024-01-01", "2024-01-03"])), "NT")


def test_run_dispatches_a_family_on_the_same_folds(monkeypatch):
    """A model of another family gets the same training days, weights and target, and its predictions are scored."""
    days = pd.date_range("2021-09-01", "2024-09-30")
    raw = _frame(days)
    w = pd.concat({("sampled", "gas"): raw}, axis=1)
    w[("sampled", "gas", "t2m_heat")] = raw["t2m"] - 1
    e = pd.DataFrame({"target": 300 - 10 * raw["t2m"], "cwv_official": np.nan}, index=days)
    e["target_repaired"] = e["target"]
    frames = {"NT": pd.concat([w, e], axis=1)}
    seen = {}

    def fit(data, weights, model):
        frame, train = data["NT"]
        seen.update(train_days=frame.index[train], weights=weights, t2m=frame["t2m"])
        return {"NT": types.SimpleNamespace(success=True, n_train=int(train.sum()))}

    def predict(fit, frame):
        return frame["target"].to_numpy() + 1.0

    family = types.SimpleNamespace(fit=fit, predict=predict, params=lambda f: {"note": "fake"})
    monkeypatch.setitem(sys.modules, "ldz_demand.models.fake", family)
    model = ex.Model("fake", "sampled_gas", half_life=1.0, target="target_repaired", temperature="t2m_heat",
                     family="fake")
    pred, params = ex.run(frames, ["NT"], [model], "forward")
    assert set(pred["held_out"]) == {"2023/24"}
    assert seen["train_days"].min() == pd.Timestamp("2021-10-01") and seen["train_days"].max() == pd.Timestamp("2023-09-30")
    assert seen["weights"] is not None and np.allclose(seen["t2m"], raw["t2m"].loc[seen["t2m"].index] - 1)
    assert np.allclose(pred["predicted"] - pred["actual"], 1.0) and pred["cwv"].isna().all()
    assert params.loc[0, "note"] == "fake" and params.loc[0, "n_train"] == len(seen["train_days"])
