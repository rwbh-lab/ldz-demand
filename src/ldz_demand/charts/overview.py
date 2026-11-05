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
    days: int            # forecast days with a closed-out (D+6) actual, all leads
    coverage: float      # share of those inside P10-P90
    lead1_error: float   # mean absolute error of the median at lead day 1, % of actual


def live_record(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str = "GB") -> LiveRecord | None:
    """The live forecasts so far, for one LDZ (runs as forecasts.wide() gives them); None before any actual."""
    v = fch.verification(runs, fch.closed_out(actual), ldz)
    if v.empty:
        return None
    lead1 = v[v["lead_days"] == 1]["error %"].abs()
    return LiveRecord(runs=runs["run_date"].nunique(), first_run=pd.Timestamp(runs["run_date"].min()),
                      days=len(v), coverage=float(v["in 10–90%"].mean()) * 100,
                      lead1_error=float(lead1.mean()) if not lead1.empty else float("nan"))


@dataclass(frozen=True)
class Outlook:
    tomorrow: pd.Series   # the lead-1 row of the latest run (gas_day, p10, p50, p90, ...)
    peak: pd.Series       # the day with the highest median
    low: pd.Series        # the day with the lowest median
    last: pd.Series       # the last forecast day
    spread_tomorrow: float  # half the 10-90% range, % of the median
    spread_last: float
    takeaway: str         # the fortnight in one line, for the chart title


SHIFT = 5.0  # % change in the median, from tomorrow, that counts as demand rising or easing


def outlook(latest: pd.DataFrame, ldz: str = "GB") -> Outlook:
    """The latest run for one LDZ, read for the page's first lines: tomorrow, the peak and low of the
    fortnight, how wide the range gets, and a one-line takeaway for the chart's title."""
    f = latest[latest["ldz"] == ldz].sort_values("gas_day")
    ahead = f[f["lead_days"] >= 1]
    tomorrow, last = ahead.iloc[0], ahead.iloc[-1]
    peak, low = ahead.loc[ahead["p50"].idxmax()], ahead.loc[ahead["p50"].idxmin()]

    def spread(r: pd.Series) -> float:
        return float((r["p90"] - r["p10"]) / 2 / r["p50"] * 100)

    up = (peak["p50"] / tomorrow["p50"] - 1) * 100
    down = (1 - low["p50"] / tomorrow["p50"]) * 100
    if up >= SHIFT and (up >= down or peak["gas_day"] < low["gas_day"]):
        takeaway = f"Demand climbs about {up:.0f}% to a peak on {peak['gas_day']:%a %d %b}"
    elif down >= SHIFT:
        takeaway = f"Demand eases about {down:.0f}% by {low['gas_day']:%a %d %b}"
    else:
        takeaway = f"Demand holds near {tomorrow['p50']:,.0f} GWh/day through the fortnight"
    return Outlook(tomorrow, peak, low, last, spread(tomorrow), spread(last), takeaway)


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
