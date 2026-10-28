"""
The Overview page's numbers: the headline scores (from the results bundle, so they follow a refit), the
live record so far, and the worked example (the quick start's sample run, forecast into a temporary folder).
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ldz_demand.charts import forecasts as fch


@dataclass(frozen=True)
class Headline:
    cold: float          # % change in GB RMSE against the official CWV, coldest days
    winter: float
    all_days: float
    ldz_better: int      # LDZs where the final model beats the official CWV over all days
    ldz_count: int
    days: int            # GB days scored


def headline(experiments: pd.DataFrame) -> Headline:
    """The final model against the official CWV, forward-scored (experiments.csv)."""
    final = experiments[(experiments["experiment"] == "final") & (experiments["scheme"] == "forward")]
    scores = final.pivot_table(index="ldz", columns="input", values=["rmse_all", "rmse_winter", "rmse_cold"])

    def change(metric: str) -> float:
        return float((scores.loc["GB", (metric, "final")] / scores.loc["GB", (metric, "official")] - 1) * 100)

    ldzs = scores.drop(index="GB")
    better = int((ldzs[("rmse_all", "final")] < ldzs[("rmse_all", "official")]).sum())
    days = int(final[(final["ldz"] == "GB") & (final["input"] == "final")]["days"].iloc[0])
    return Headline(change("rmse_cold"), change("rmse_winter"), change("rmse_all"), better, len(ldzs), days)


@dataclass(frozen=True)
class LiveRecord:
    runs: int
    first_run: pd.Timestamp
    days: int            # forecast days with an actual (all leads)
    coverage: float      # share of those inside P10-P90
    lead1_error: float   # mean absolute error of the median at lead day 1, % of actual


def live_record(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str = "GB") -> LiveRecord | None:
    """The live forecasts so far, for one LDZ (runs as forecasts.wide() gives them); None before any actual."""
    v = fch.verification(runs, actual, ldz)
    if v.empty:
        return None
    lead1 = v[v["lead_days"] == 1]["error %"].abs()
    return LiveRecord(runs=runs["run_date"].nunique(), first_run=pd.Timestamp(runs["run_date"].min()),
                      days=len(v), coverage=float(v["in 10–90%"].mean()) * 100,
                      lead1_error=float(lead1.mean()) if not lead1.empty else float("nan"))


def worked_example() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The quick start's sample run (5 Jan 2025) forecast afresh: (runs as forecasts.wide() gives them, actuals).
    Uses a temporary folder, so the user's data/quickstart/ is left alone."""
    from ldz_demand import quickstart
    from ldz_demand.data.datasets import DEMAND_FORECAST_DAILY
    from ldz_demand.data.store.csv_cache import CsvCacheStore
    from ldz_demand.models import forecast as fcm

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "quickstart"
        quickstart.run(work)
        store = CsvCacheStore(work)
        return fch.wide(store.read(DEMAND_FORECAST_DAILY)), fcm.actuals(store)
