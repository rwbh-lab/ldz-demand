import pandas as pd
import pytest

from ldz_demand.charts import overview as ov
from ldz_demand.models import results


def test_headline_reads_the_final_model_against_the_official_cwv():
    h = ov.headline(results.load("experiments"))
    assert h.cold < h.winter < 0 and h.all_days < 0     # better, and most of all on cold days
    assert h.ldz_count == 13 and 0 < h.ldz_better <= 13 and h.days > 0


def test_live_record_counts_runs_coverage_and_the_lead_one_error():
    days = pd.date_range("2026-10-13", periods=3)
    runs = pd.DataFrame({"run_date": [days[0], days[0], days[1]], "ldz": "GB",
                         "gas_day": [days[0], days[1], days[2]], "lead_days": [0, 1, 1],
                         "p10": 90.0, "p50": 100.0, "p90": 110.0, "weather_p10": 95.0, "weather_p90": 105.0})
    actual = pd.DataFrame({"gas_day": days, "ldz": "GB", "actual": [100.0, 125.0, 95.0], "provisional": False})
    r = ov.live_record(runs, actual)
    assert (r.runs, r.days, r.first_run) == (2, 3, days[0])
    assert r.coverage == pytest.approx(200 / 3)           # 125 is outside 90-110
    assert r.lead1_error == pytest.approx((20 + 100 / 95 * 5) / 2, rel=1e-3)
    assert ov.live_record(runs, actual.iloc[:0]) is None
