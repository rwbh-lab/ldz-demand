"""
A compact copy of the experiment results, shipped with the package for the dashboard's Backtesting results page.

The experiments write their full outputs to data/results/ (tens of MB, not committed). This keeps the
small tables the page needs, under ldz_demand/models/data/results/:

- experiments.csv:   every experiment's scores, GB and per LDZ (RMSE / MAPE, all days, winter, coldest);
- final_daily.csv:   GB per gas day, forward: actual, the final model, the official CWV;
- final_monthly.csv: GB by month: bias, RMSE and MAPE, the final model and the official CWV;
- benchmark.csv:     GB per gas day: total demand, National Gas's day-ahead forecast, ours;
- final_residuals.csv: per LDZ and gas day, the final model's out-of-sample error as a ratio
                     (actual / predicted - 1) — the model-error part of the forecast intervals.

    python -m ldz_demand.models.results     # after the experiments and the benchmark
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ldz_demand.data import ldz_energy as le
from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.models.experiment import RESULTS

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data" / "results"
EXPERIMENTS = {  # name -> (number, what it tests, scheme)
    "cwv_inputs": ("1", "Weather input", "held out"),
    "variables": ("2", "Variables", "forward"),
    "seasonal": ("3", "Seasonal term", "held out"),
    "change": ("4", "Change over time", "forward"),
    "averaging": ("5", "Gas-day averaging", "forward"),
    "target": ("6", "Target A vs B", "forward"),
    "final": ("final", "The final model", "forward"),
}
def _round(df: pd.DataFrame, n: int = 2) -> pd.DataFrame:
    return df.round({c: n for c in df.select_dtypes("number").columns})


HEADER = ("# Derived by ldz-demand (python -m ldz_demand.models.results) from National Gas LDZ demand and forecasts\n"
          "# (data.nationalgas.com) and ERA5 (contains modified Copernicus Climate Change Service information).\n")


def experiments_table() -> pd.DataFrame:
    rows = []
    for name, (number, title, scheme) in EXPERIMENTS.items():
        path = RESULTS / f"{name}_scores.csv"
        if not path.exists():
            logger.warning(f"{path.name} missing — run python -m ldz_demand.models.experiment {name}")
            continue
        s = pd.read_csv(path).assign(experiment=name, number=number, title=title, scheme=scheme)
        rows.append(s)
    out = pd.concat(rows, ignore_index=True)
    cols = ["number", "experiment", "title", "scheme", "ldz", "input", "days", "rmse_all", "rmse_winter", "rmse_cold",
            "mape_all", "mape_winter", "mape_cold"]
    return _round(out[cols], 3)


def final_daily() -> pd.DataFrame:
    """GB per gas day (days with all 13 LDZs, real days only): actual and both models' predictions."""
    p = pd.read_csv(RESULTS / "final_predictions.csv", parse_dates=["gas_day"])
    p = p[~p["repaired"].astype(bool)]
    p = p[p.groupby(["ldz", "gas_day"])["input"].transform("nunique") == p["input"].nunique()]
    gb = p.groupby(["input", "gas_day"]).agg(actual=("actual", "sum"), predicted=("predicted", "sum"),
                                              n=("ldz", "nunique"), held_out=("held_out", "first")).reset_index()
    gb = gb[gb["n"] == len(LDZS)]
    wide = gb.pivot_table(index=["gas_day", "held_out"], columns="input", values="predicted").reset_index()
    actual = gb.drop_duplicates("gas_day").set_index("gas_day")["actual"]
    wide["actual"] = wide["gas_day"].map(actual)
    return _round(wide)


def final_daily_ours() -> pd.DataFrame:
    """As final_daily, but the final model alone — so 2025/26, which the official CWV can't be scored on, is in."""
    p = pd.read_csv(RESULTS / "final_predictions.csv", parse_dates=["gas_day"])
    p = p[(p["input"] == "final") & ~p["repaired"].astype(bool)]
    gb = p.groupby("gas_day").agg(actual=("actual", "sum"), final=("predicted", "sum"), n=("ldz", "nunique"),
                                  held_out=("held_out", "first")).reset_index()
    return _round(gb[gb["n"] == len(LDZS)].drop(columns="n"))


def monthly(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model in [c for c in ("final", "official") if c in daily]:
        d = daily.dropna(subset=[model])
        err = d[model] - d["actual"]
        g = pd.DataFrame({"month": d["gas_day"].dt.to_period("M").dt.to_timestamp(), "err": err,
                          "ape": err.abs() / d["actual"] * 100}).groupby("month")
        rows.append(pd.DataFrame({"model": model, "bias": g["err"].mean(), "rmse": g["err"].apply(lambda e: np.sqrt((e ** 2).mean())),
                                  "mape": g["ape"].mean(), "days": g.size()}).reset_index())
    return _round(pd.concat(rows, ignore_index=True))


def benchmark() -> pd.DataFrame:
    x = pd.read_csv(RESULTS / "ng_forecast_comparison.csv", parse_dates=["gas_day"])
    gb = x.groupby(["held_out", "gas_day"]).agg(n=("ldz", "nunique"), total=("total", "sum"), ng=("ng", "sum"),
                                                ours=("ours", "sum")).reset_index()
    return _round(gb[gb["n"] == len(LDZS)].drop(columns="n"))


def final_residuals() -> pd.DataFrame:
    """Per LDZ and gas day (real days, every LDZ present): actual / predicted - 1, the final model, forward."""
    p = pd.read_csv(RESULTS / "final_predictions.csv", parse_dates=["gas_day"])
    p = p[(p["input"] == "final") & ~p["repaired"].astype(bool) & (p["predicted"] > 0)]
    p = p[p.groupby("gas_day")["ldz"].transform("nunique") == len(LDZS)]
    out = p.assign(ratio=p["actual"] / p["predicted"] - 1)[["gas_day", "ldz", "ratio"]]
    return out.round({"ratio": 5})


def export(out_dir: Path = DATA_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    daily = final_daily()
    ours = final_daily_ours()
    both = ours.merge(daily[["gas_day", "official"]], on="gas_day", how="left")
    tables = {"experiments": experiments_table(), "final_daily": both, "final_monthly": monthly(both),
              "benchmark": benchmark(), "final_residuals": final_residuals()}
    paths = {}
    for name, df in tables.items():
        path = out_dir / f"{name}.csv"
        with open(path, "w") as f:
            f.write(HEADER)
            df.to_csv(f, index=False)
        paths[name] = path
        logger.info(f"{path.name}: {len(df)} rows")
    return paths


def load(name: str) -> pd.DataFrame:
    """One of the exported tables (experiments, final_daily, final_monthly, benchmark)."""
    df = pd.read_csv(DATA_DIR / f"{name}.csv", comment="#")
    for col in ("gas_day", "month"):
        if col in df:
            df[col] = pd.to_datetime(df[col])
    return df


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    export()
    return 0


if __name__ == "__main__":
    sys.exit(main())
