"""
The final demand model, fitted on every usable day and saved with the package (docs/results.md, summary).

What the experiments chose: target B; gas-weighted ERA5 with the gas-day temperature weighted to the
heating hours (models.averaging, "peaks"), wind and solar; our CWV form with the calendar shape shared by
all LDZs and the fitted cold-weather upturn; demand linear in the CWV plus calendar terms; training days
weighted by recency (half-life 1 year), counted back from the last training day. All 13 LDZs are fitted
together (the shape is shared).

    python -m ldz_demand.models.fit      # fit and write ldz_demand/models/data/final_fit.csv

load() rebuilds the fitted models (demand.Fit per LDZ) for predicting. The temperature they expect is the
heating-hours gas-day mean — build it with models.averaging, not the daily table's flat mean.
"""

import argparse
import logging
import sys
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.models import cwv, demand
from ldz_demand.models import experiment as ex

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
OUTPUT = "final_fit.csv"
TEMPERATURE = ("peaks", 1)  # gas-day temperature: (averaging profile, step hours)
MODEL = ex.BEST            # target B, recency half-life 1 year, calendar shape, gas-weighted input

HEADER = (
    "# Derived by ldz-demand (python -m ldz_demand.models.fit): the fitted LDZ demand model, one row per LDZ.\n"
    "# Fitted to National Gas LDZ demand (data.nationalgas.com) and ERA5 reanalysis (contains modified Copernicus\n"
    "# Climate Change Service information; neither the European Commission nor ECMWF is responsible for any use).\n"
    "# p_*: CWV parameters (ldz_demand.models.cwv); c_*: linear terms; shape_*: the calendar shape (shared).\n"
)


def fit(frames: dict[str, pd.DataFrame] | None = None, ldzs=LDZS) -> dict[str, demand.Fit]:
    """The final model per LDZ, fitted on every usable day of the gas years in experiment.GAS_YEARS."""
    frames = frames or ex.averaged_frames(ex.load(), *TEMPERATURE)
    data, weights = {}, {}
    for ldz in ldzs:
        d, _, usable = ex._prepared(frames[ldz], MODEL.input, MODEL.target)
        data[ldz] = (d, usable)
        weights[ldz] = demand.recency_weights(d.index, usable, MODEL.half_life)
    return demand.fit_joint(data, MODEL.seasonal, MODEL.breaks, weights, MODEL.summer, MODEL.cold, MODEL.extremes,
                            MODEL.solar)


def to_frame(fits: dict[str, demand.Fit], frames: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """One row per LDZ: CWV parameters, linear terms, the shared shape, and what was fitted."""
    rows = []
    for ldz, f in fits.items():
        row = {"ldz": ldz, "n_train": f.n_train, "success": f.success}
        row.update({f"p_{k}": v for k, v in asdict(f.params).items()})
        row.update({f"c_{k}": v for k, v in zip(f.columns, f.coef)})
        row.update({f"shape_{i + 1}": v for i, v in enumerate(f.shape)})
        rows.append(row)
    out = pd.DataFrame(rows)
    out["seasonal"], out["temperature"], out["target"] = MODEL.seasonal, f"{TEMPERATURE[0]}_{TEMPERATURE[1]}h", MODEL.target
    out["half_life_years"], out["fitted_on"] = MODEL.half_life, date.today().isoformat()
    if frames is not None:
        out["train_from"] = [str(frames[ldz].index[frames[ldz]["target_repaired"].notna()].min().date()) for ldz in fits]
    return out


def save(fits: dict[str, demand.Fit], frames=None, out_dir: Path = DATA_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / OUTPUT
    with open(path, "w") as f:
        f.write(HEADER)
        to_frame(fits, frames).to_csv(f, index=False, float_format="%.8g")
    return path


def load(path: Path = DATA_DIR / OUTPUT) -> dict[str, demand.Fit]:
    """The saved final model: a demand.Fit per LDZ, ready for demand.predict."""
    df = pd.read_csv(path, comment="#")
    names = [f.name for f in fields(cwv.CWVParams)]
    coef_cols = [c for c in df.columns if c.startswith("c_")]
    shape_cols = sorted((c for c in df.columns if c.startswith("shape_")), key=lambda c: int(c.split("_")[1]))
    fits = {}
    for _, r in df.iterrows():
        params = cwv.CWVParams(**{n: float(r[f"p_{n}"]) for n in names})
        fits[r["ldz"]] = demand.Fit("weather", r["ldz"], r[coef_cols].to_numpy(dtype=float), [c[2:] for c in coef_cols],
                                    params, bool(r["success"]), int(r["n_train"]), str(r["seasonal"]),
                                    shape=r[shape_cols].to_numpy(dtype=float))
    return fits


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m ldz_demand.models.fit").parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    frames = ex.averaged_frames(ex.load(), *TEMPERATURE)
    fits = fit(frames)
    path = save(fits, frames)
    in_sample = {}
    for ldz, f in fits.items():
        d, _, usable = ex._prepared(frames[ldz], MODEL.input, MODEL.target)
        err = demand.predict(f, d)[usable] - d["target"].to_numpy()[usable]
        in_sample[ldz] = float(np.sqrt(np.mean(err ** 2)))
    logger.info(f"In-sample RMSE (GWh/day, all training days, unweighted): "
                f"{', '.join(f'{k} {v:.2f}' for k, v in in_sample.items())}")
    logger.info(f"All converged: {all(f.success for f in fits.values())}. Written {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
