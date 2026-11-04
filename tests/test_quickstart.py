import pandas as pd

from ldz_demand import quickstart
from ldz_demand.data.datasets import DEMAND_FORECAST_DAILY
from ldz_demand.data.store.csv_cache import CsvCacheStore
from ldz_demand.models import forecast as fcm


def test_the_sample_run_forecasts_every_lead_day_with_actuals(tmp_path):
    gb = quickstart.run(tmp_path / "quickstart")
    assert list(gb["lead_days"]) == list(fcm.LEAD_DAYS)
    assert (gb["p10"] < gb["p50"]).all() and (gb["p50"] < gb["p90"]).all()
    assert gb["actual"].notna().all()
    # the cold spell (8-11 Jan 2025) is in the forecast: its peak beats the run day's
    assert gb.loc["2025-01-08":"2025-01-11", "p50"].max() > gb["p50"].iloc[0]


def test_actuals_since_a_day_match_the_full_read_from_that_day():
    store = CsvCacheStore(quickstart.SAMPLE)
    full = fcm.actuals(store)
    since = full["gas_day"].min() + pd.Timedelta(days=7)
    trimmed = fcm.actuals(store, since=since)
    expected = full[full["gas_day"] >= since].reset_index(drop=True)
    assert not trimmed.empty and trimmed["gas_day"].min() == since
    pd.testing.assert_frame_equal(trimmed.reset_index(drop=True), expected)


def test_the_dashboard_can_read_the_result(tmp_path):
    work = tmp_path / "quickstart"
    quickstart.run(work)
    stored = CsvCacheStore(work).read(DEMAND_FORECAST_DAILY)
    assert set(stored["ldz"]) >= {"GB", "NT", "SC"}
    assert pd.to_datetime(stored["run_date"]).dt.date.unique().tolist() == [quickstart.RUN.date()]


def test_actuals_carry_a_range_around_each_value():
    a = fcm.actuals(CsvCacheStore(quickstart.SAMPLE))
    assert {"lo", "hi"} <= set(a.columns) and not a[["lo", "hi"]].isna().any().any()
    assert ((a["lo"] <= a["actual"] + 1e-9) & (a["actual"] <= a["hi"] + 1e-9)).all()
    final = a[~a["provisional"]]
    assert ((final["hi"] / final["actual"] - 1).round(6) == fcm.METER_TOLERANCE).all()


def test_a_provisional_range_follows_the_usual_revision():
    # D+1 has always read 10% above D+6: a provisional 110 should be expected to close out near 100
    days = pd.date_range("2025-01-01", periods=60)
    hist = pd.DataFrame({"gas_day": days, "ldz": "NT", "d6": 100.0, "d1": 110.0})
    today = pd.DataFrame({"gas_day": [pd.Timestamp("2025-03-02")], "ldz": "NT", "d6": [float("nan")], "d1": [110.0]})
    out = pd.concat([hist, today], ignore_index=True)
    out["actual"], out["provisional"] = out["d6"].fillna(out["d1"]), out["d6"].isna()
    r = fcm._with_ranges(out).iloc[-1]
    assert abs(r["lo"] - 100) < 1e-6 and abs(r["hi"] - 100) < 1e-6
