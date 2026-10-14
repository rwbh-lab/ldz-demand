"""
Our model against National Gas's own day-ahead forecasts (docs/results.md).

National Gas publishes a total-demand forecast per LDZ, ~8 issues per gas day (ng_forecast_daily); the
first day-ahead issue is at ~13:00 on D-1. It is compared with our final model (experiment "final",
scored forward — the model in models.fit), both on total demand in GWh: theirs converted from mcm with the day's CV,
ours as our prediction of total - DM plus the actual DM (so the error is the same as on our target).

Not like for like, in two directions: ours uses actual weather (ERA5), theirs a day-ahead forecast; and
theirs includes forecasting DM, ours doesn't. The weather part is estimated from their forecast CWV
(the 12:00 day-ahead issue) against the actual CWV.

Run (after `python -m ldz_demand.models.experiment final`):
    python -m ldz_demand.models.benchmark
Writes data/results/ng_forecast_comparison.csv.
"""

import logging
import sys

import numpy as np
import pandas as pd

from ldz_demand.config import create_config
from ldz_demand.data import ldz_energy as le
from ldz_demand.data.datasets import NG_FORECAST_DAILY, NG_LDZ_DAILY, NG_OFFTAKE_DAILY
from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.data.store import get_store
from ldz_demand.models.experiment import RESULTS

logger = logging.getLogger(__name__)

EXPERIMENT, MODEL = "final", "final"
CWV_ISSUE_HOUR = 12


def comparison(store=None, predictions: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per LDZ and gas day (ok days only): total, National Gas's forecast, ours, their CWV error."""
    store = store or get_store(create_config())
    f = store.read(NG_FORECAST_DAILY)
    f["gas_day"] = pd.to_datetime(f["gas_day"])
    day_ahead = f[f["issue_day"] == -1].sort_values("issued_at")
    demand = (day_ahead[day_ahead["item"] == "demand_forecast"].groupby(["gas_day", "ldz"]).first().reset_index()
              [["gas_day", "ldz", "value", "issued_at"]].rename(columns={"value": "ng_mcm"}))
    cwv = day_ahead[(day_ahead["item"] == "cwv_forecast_d_minus_1") & (day_ahead["issued_at"].dt.hour == CWV_ISSUE_HOUR)]
    cwv = cwv.groupby(["gas_day", "ldz"])["value"].first().rename("cwv_forecast").reset_index()
    e = le.energy_frame(store.read(NG_LDZ_DAILY), store.read(NG_OFFTAKE_DAILY)).reset_index()
    e = e[e["ldz"] != le.GB][["gas_day", "ldz", "total", "dm", "target", "cv", "cwv"]]
    e["gas_day"] = pd.to_datetime(e["gas_day"])
    if predictions is None:
        predictions = pd.read_csv(RESULTS / f"{EXPERIMENT}_predictions.csv", parse_dates=["gas_day"])
    ours = predictions[predictions["input"] == MODEL][["gas_day", "ldz", "held_out", "predicted"]]
    x = e.merge(demand, on=["gas_day", "ldz"]).merge(cwv, on=["gas_day", "ldz"], how="left").merge(ours, on=["gas_day", "ldz"])
    x = x[x["target"].notna()].copy()
    x["ng"] = x["ng_mcm"] * x["cv"] / 3.6
    x["ours"] = x["predicted"] + x["dm"]
    x["cwv_error"] = x["cwv_forecast"] - x["cwv"]
    return x


def gb_scores(x: pd.DataFrame) -> pd.DataFrame:
    """GB (days with all 13 LDZs): % error, RMSE and bias per held-out year and season."""
    gb = x.groupby(["held_out", "gas_day"]).agg(n=("ldz", "nunique"), total=("total", "sum"), ng=("ng", "sum"),
                                                ours=("ours", "sum")).reset_index()
    gb = gb[gb["n"] == len(LDZS)]
    gb["season"] = np.where(gb["gas_day"].dt.month.isin([11, 12, 1, 2, 3]), "winter", "summer")
    rows = []
    for (year, season), g in pd.concat([gb, gb.assign(season="all")]).groupby(["held_out", "season"]):
        for k in ("ng", "ours"):
            err = g[k] - g["total"]
            ape = err.abs() / g["total"] * 100
            rows.append({"held_out": year, "season": season, "forecast": k, "days": len(g), "mape": ape.mean(),
                         "median_ape": ape.median(), "rmse": float(np.sqrt((err ** 2).mean())), "bias": err.mean()})
    return pd.DataFrame(rows)


def weather_part(x: pd.DataFrame) -> pd.DataFrame:
    """Per LDZ: their RMSE, and with the part following their CWV forecast error removed; ours."""
    rows = []
    for ldz, g in x.dropna(subset=["cwv_error"]).groupby("ldz"):
        err_ng, err_ours = g["ng"] - g["total"], g["ours"] - g["total"]
        slope = np.polyfit(g["cwv_error"], err_ng, 1)[0]
        rows.append({"ldz": ldz, "slope": slope, "rmse_ng": float(np.sqrt((err_ng ** 2).mean())),
                     "rmse_ng_weather_removed": float(np.sqrt(((err_ng - slope * g["cwv_error"]) ** 2).mean())),
                     "rmse_ours": float(np.sqrt((err_ours ** 2).mean()))})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    x = comparison()
    x.to_csv(RESULTS / "ng_forecast_comparison.csv", index=False)
    pd.set_option("display.width", 200)
    logger.info(f"GB, total demand:\n{gb_scores(x).round(1).to_string(index=False)}")
    w = x["cwv_error"].dropna()
    logger.info(f"Their day-ahead CWV error: mean abs {w.abs().mean():.2f} °C, RMSE {np.sqrt((w ** 2).mean()):.2f} °C")
    logger.info(f"Per LDZ, RMSE (GWh/day):\n{weather_part(x).round(2).to_string(index=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
