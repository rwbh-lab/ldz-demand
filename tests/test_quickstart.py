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


def test_the_dashboard_can_read_the_result(tmp_path):
    work = tmp_path / "quickstart"
    quickstart.run(work)
    stored = CsvCacheStore(work).read(DEMAND_FORECAST_DAILY)
    assert set(stored["ldz"]) >= {"GB", "NT", "SC"}
    assert pd.to_datetime(stored["run_date"]).dt.date.unique().tolist() == [quickstart.RUN.date()]
