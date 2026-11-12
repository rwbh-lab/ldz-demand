"""
Where the CWV model goes wrong: a shallow regression tree on its held-out errors (the challenger work).

The tree doesn't forecast. It looks for groups of days where the final model's forward errors (from
the challenger or final experiment) lean one way, using candidate inputs the model has and some it
hasn't. A split on a candidate the model lacks is a feature worth testing; a split on one it has is
something its form doesn't capture. Every candidate must exist at forecast time: in the ECMWF ensemble
(temperature, wind, solar, precipitation, the daily min / max) or known in advance (the calendar).

The error is in % of the LDZ's mean demand, so the 13 LDZs share one tree. The honest test is by gas
year: the tree is grown on two held-out years and scored on the third. If it explains little of the
third, there is little systematic left to find.

The tree's splits are then checked one at a time (consistency): each candidate group's error against
the rest, per held-out year, after taking out each LDZ-year's level (the drift between years). A
feature is worth testing only if its group leans the same way in every year. Two did, on the final
model's forward errors (12 Nov 2026): cold weekends against cold weekdays, and bridge days; cold
spells, school holidays and early October flipped sign (docs/challenger.md).

School holidays are approximate (England-style dates, not each authority's): October half-term (the
last full week of October), February half-term (the week of the third Monday), and Easter (Good Friday
± a week). Good enough to ask whether they matter.

Run:
    python -m ldz_demand.models.diagnostics                  # the challenger experiment's predictions
    python -m ldz_demand.models.diagnostics --depth 4
"""

import argparse
import logging
import sys

import numpy as np
import pandas as pd

from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.models import calendar
from ldz_demand.models import experiment as ex
from ldz_demand.models.features import features

logger = logging.getLogger(__name__)

COLD_RUN_BELOW = 3.0   # °C: a cold spell's days
MIN_LEAF_SHARE = 0.02  # of the rows, at least MIN_LEAF rows
MIN_LEAF = 200


def _school_holidays(days: pd.DatetimeIndex, ldz: str) -> np.ndarray:
    out = np.zeros(len(days), bool)
    for year in range(days.year.min(), days.year.max() + 1):
        oct27 = pd.Timestamp(f"{year}-10-27")  # the last Monday whose Monday-Friday is inside October
        last_mon = oct27 - pd.Timedelta(days=oct27.day_of_week)
        feb = pd.date_range(f"{year}-02-01", f"{year}-02-28")
        third_mon = feb[feb.day_of_week == 0][2]
        for start in (last_mon, third_mon):
            out |= (days >= start) & (days <= start + pd.Timedelta(days=4))
    cal = calendar.features(days, ldz)
    good_fridays = days[(cal["bank_holiday"] == 1).to_numpy() & (days.day_of_week == 4) & days.month.isin([3, 4])]
    for gf in good_fridays:
        out |= (days >= gf - pd.Timedelta(days=7)) & (days <= gf + pd.Timedelta(days=10))
    return out


def candidates(frame: pd.DataFrame, ldz: str) -> pd.DataFrame:
    """The model's own inputs (models.features) and others, one row per row of frame (consecutive gas days)."""
    f = features(frame, ldz)
    t = frame["t2m"].astype(float)
    f["dt"] = f["t"] - f["t_lag1"]
    f["t_week"] = t.shift(1).rolling(7, min_periods=7).mean().to_numpy()  # longer memory than the CWV's
    cold = (t < COLD_RUN_BELOW).to_numpy()
    run = np.zeros(len(cold), int)
    for i, c in enumerate(cold):
        run[i] = run[i - 1] + 1 if c and i else int(c)
    f["cold_run"] = run
    for c in ("tmin", "tmax", "tp"):
        f[c] = frame[c].to_numpy(dtype=float) if c in frame else np.nan
    f["t_range"] = f["tmax"] - f["tmin"]
    days = pd.DatetimeIndex(frame.index)
    f["bridge"] = calendar.bridge(days, ldz)
    f["school_holiday"] = _school_holidays(days, ldz)
    f["month"] = days.month
    f["gas_year"] = np.where(days.month >= 10, days.year, days.year - 1)
    return f.astype(float)


def residual_table(predictions: pd.DataFrame, frames: dict[str, pd.DataFrame], label: str = "final") -> pd.DataFrame:
    """Per LDZ and held-out day: the error (predicted − actual) in % of the LDZ's mean actual, and the candidates."""
    p = predictions[(predictions["input"] == label) & ~predictions["repaired"].astype(bool)].copy()
    p["gas_day"] = pd.to_datetime(p["gas_day"])
    model = ex.FINAL
    out = []
    for ldz, g in p.groupby("ldz"):
        data = ex._prepared(frames[ldz], model.input, model.target, model.temperature)[0]
        c = candidates(data, ldz).reindex(g["gas_day"])
        c["error_pct"] = ((g["predicted"] - g["actual"]) / g["actual"].mean() * 100).to_numpy()
        c["held_out"], c["ldz"] = g["held_out"].to_numpy(), ldz
        out.append(c.reset_index(names="gas_day"))
    return pd.concat(out, ignore_index=True)


def _x(table: pd.DataFrame) -> pd.DataFrame:
    x = table.drop(columns=["gas_day", "error_pct", "held_out", "ldz"])
    return pd.concat([x, pd.get_dummies(table["ldz"], prefix="ldz", dtype=float)], axis=1)


def grow(table: pd.DataFrame, depth: int = 3):
    from sklearn.tree import DecisionTreeRegressor

    leaf = max(MIN_LEAF, int(MIN_LEAF_SHARE * len(table)))
    return DecisionTreeRegressor(max_depth=depth, min_samples_leaf=leaf, random_state=0).fit(
        _x(table).fillna(-999), table["error_pct"])


def by_year(table: pd.DataFrame, depth: int = 3) -> pd.DataFrame:
    """Grown on the other held-out years, scored on each: the share of its error variance explained, and the root split."""
    rows = []
    for year in sorted(table["held_out"].unique()):
        train, test = table[table["held_out"] != year], table[table["held_out"] == year]
        tree = grow(train, depth)
        e = test["error_pct"].to_numpy()
        pred = tree.predict(_x(test).reindex(columns=_x(train).columns, fill_value=0).fillna(-999))
        root = _x(train).columns[tree.tree_.feature[0]]
        rows.append({"scored_on": year, "days": len(test), "rmse_pct": float(np.sqrt(np.mean(e ** 2))),
                     "explained": float(1 - np.mean((e - pred) ** 2) / np.mean((e - e.mean()) ** 2)),
                     "root": f"{root} <= {tree.tree_.threshold[0]:.2f}"})
    return pd.DataFrame(rows)


HEATING_SEASON_DAYS = 240  # 1 Oct - late May: the groups below are compared within it
COLD_TMAX = 6.5            # °C: a cold day by its warmest hour (the tree's split)
GROUPS = {  # name -> (the days compared, the group within them); the effect is the group's mean minus the rest's
    "cold weekend vs cold weekday": (lambda t: t["tmax"] <= COLD_TMAX, lambda t: t["weekday"] >= 5),
    "bridge day": (lambda t: t["season_day"] <= HEATING_SEASON_DAYS, lambda t: t["bridge"] == 1),
    "cold spell (3+ days below 3 °C)": (lambda t: t["season_day"] <= HEATING_SEASON_DAYS, lambda t: t["cold_run"] >= 3),
    "school holiday (approx.)": (lambda t: t["season_day"] <= HEATING_SEASON_DAYS, lambda t: t["school_holiday"] == 1),
    "first half of October vs 16-23 Oct": (lambda t: t["season_day"] <= 23, lambda t: t["season_day"] <= 15),
}


def consistency(table: pd.DataFrame) -> pd.DataFrame:
    """Per candidate group and held-out year: the group's mean error minus the rest's (% of mean demand,
    each LDZ-year's level taken out), the group's LDZ-days, and whether every year leans the same way."""
    t = table.assign(e=table["error_pct"] - table.groupby(["ldz", "held_out"])["error_pct"].transform("mean"))
    rows = []
    for name, (among, group) in GROUPS.items():
        sub = t[among(t)]
        g = group(sub)
        for year, y in sub.groupby("held_out"):
            gy = g.loc[y.index]
            rows.append({"group": name, "held_out": year, "days": int(gy.sum()),
                         "effect_pct": float(y.loc[gy, "e"].mean() - y.loc[~gy, "e"].mean())})
    out = pd.DataFrame(rows)
    signs = out.groupby("group")["effect_pct"].apply(lambda e: bool((e > 0).all() or (e < 0).all()))
    return out.assign(consistent=out["group"].map(signs))


def persistence(table: pd.DataFrame) -> pd.Series:
    """Lag-1 autocorrelation of the error per LDZ: how much of today's error was there yesterday (weather can't explain it)."""
    out = {}
    for ldz, g in table.sort_values("gas_day").groupby("ldz"):
        e = g.set_index("gas_day")["error_pct"].asfreq("D")
        out[ldz] = e.autocorr(1)
    return pd.Series(out, name="lag1_autocorr")


def main(argv: list[str] | None = None) -> int:
    from sklearn.tree import export_text

    parser = argparse.ArgumentParser(prog="python -m ldz_demand.models.diagnostics")
    parser.add_argument("--experiment", default="challenger")
    parser.add_argument("--depth", type=int, default=3)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    predictions = pd.read_csv(ex.RESULTS / f"{args.experiment}_predictions.csv")
    frames = ex.load()
    table = residual_table(predictions, {ldz: frames[ldz] for ldz in LDZS})
    tree = grow(table, args.depth)
    names = list(_x(table).columns)
    importance = pd.Series(tree.feature_importances_, index=names).sort_values(ascending=False)
    text = export_text(tree, feature_names=names, decimals=2)
    pd.set_option("display.width", 200)
    print(f"Errors: {len(table)} LDZ-days, mean {table['error_pct'].mean():.2f} %, RMSE {np.sqrt((table['error_pct'] ** 2).mean()):.2f} % of LDZ mean demand")
    print(f"\nTree (depth {args.depth}, all years; leaves: mean error %):\n{text}")
    print(f"Importance:\n{importance[importance > 0].round(3).to_string()}\n")
    print(f"By gas year (grown on the others):\n{by_year(table, args.depth).round(3).to_string(index=False)}\n")
    print(f"Error persistence (lag-1 autocorrelation):\n{persistence(table).round(2).to_string()}\n")
    c = consistency(table)
    wide = c.pivot(index="group", columns="held_out", values="effect_pct").round(2)
    wide["consistent"] = c.groupby("group")["consistent"].first()
    print(f"Candidate groups, error vs the rest by year (% of mean demand, + = model too high):\n{wide.to_string()}")
    table.to_csv(ex.RESULTS / "diagnostics_residuals.csv", index=False)
    c.to_csv(ex.RESULTS / "diagnostics_consistency.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
