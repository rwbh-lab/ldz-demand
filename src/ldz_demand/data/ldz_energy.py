"""
LDZ demand in energy terms, data-quality flags, and the model target.

energy_frame() turns ng_ldz_daily (+ optionally ng_offtake_daily) into one GWh/day frame per
(gas_day, ldz), plus GB sums. Total demand is published in mcm, so it is converted with the LDZ
calorific value: GWh = mcm * CV[MJ/m3] / 3.6.

Flags on the published total (worst first):
- invalid       total < INVALID_BELOW x (DM + NDM): zero / negative / near-zero — publication errors
- suspect       (only without offtake data) total < SUSPECT_BELOW x (DM + NDM)
- mismatch      total - offtakes is off its usual level by > max(MISMATCH_ABS, MISMATCH_REL x total)
- missing_feed  an LDZ with a material non-NTS input (> FEED_MATERIAL GWh/day) where that input
                drops below FEED_MISSING_SHARE of its usual level — the published total has left a
                feed out (SE, Sep 2022 - Feb 2024). Repairable: total ~= offtakes + usual input.
- ok

Two targets, so results can be checked for sensitivity to the repair:
- target          (option A) total - DM on ok days only
- target_repaired (option B) as A, plus missing_feed days using the repaired total
"""

import numpy as np
import pandas as pd

from ldz_demand.data.ingest.national_gas import LDZS

GB = "GB"  # all 13 LDZs summed

INVALID_BELOW = 0.1
SUSPECT_BELOW = 0.7
FEED_MATERIAL = 10.0       # GWh/day
FEED_MISSING_SHARE = 0.5
MISMATCH_ABS = 8.0         # GWh/day
MISMATCH_REL = 0.15

FLAGS = ("ok", "missing_feed", "mismatch", "suspect", "invalid")  # ordered best -> worst


def energy_frame(df: pd.DataFrame, offtakes: pd.DataFrame | None = None, closeout: str = "d6") -> pd.DataFrame:
    """
    Wide GWh/day frame indexed by (gas_day, ldz), plus GB rows.

    Columns: total, dm, ndm, uig, cwv, cv, ratio = total / (dm + ndm);
    with offtakes: offtake (sum of NTS offtakes), other = total - offtake, other_usual (LDZ median);
    flag (see module doc); total_repaired; target, target_repaired;
    gap = total - dm - ndm (UIG + shrinkage), residual = gap - uig (shrinkage) — ok days only.
    """
    w = df.pivot_table(index=["gas_day", "ldz"], columns="item", values="value")
    out = pd.DataFrame(index=w.index)
    out["total"] = w[f"demand_total_{closeout}"] * w["cv"] / 3.6
    for part in ("dm", "ndm", "uig"):
        out[part] = w.get(f"demand_{part}_{closeout}", np.nan) / 1e6
    out["cwv"] = w.get("cwv_actual", np.nan)
    out["cv"] = w["cv"]
    out["ratio"] = out["total"] / (out["dm"] + out["ndm"])

    if offtakes is not None and not offtakes.empty:
        sums = offtakes.groupby(["gas_day", "ldz"])["value"].sum(min_count=1) / 1e6
        out["offtake"] = sums.reindex(out.index)
        out["other"] = out["total"] - out["offtake"]
        usable = out["ratio"] >= INVALID_BELOW
        out["other_usual"] = out.index.get_level_values("ldz").map(out["other"].where(usable).groupby(level="ldz").median())
        flag = _flags_with_offtakes(out)
    else:
        out["offtake"] = out["other"] = out["other_usual"] = np.nan
        flag = pd.Series(np.select([out["ratio"] < INVALID_BELOW, out["ratio"] < SUSPECT_BELOW],
                                   ["invalid", "suspect"], "ok"), index=out.index)
    out["flag"] = pd.Categorical(flag, categories=FLAGS, ordered=True)
    out["total_repaired"] = np.where(out["flag"] == "missing_feed", out["offtake"] + out["other_usual"],
                                     out["total"].where(out["flag"] == "ok"))
    out = _derive(out)
    return pd.concat([out, _gb(out)]).sort_index()


def _flags_with_offtakes(out: pd.DataFrame) -> pd.Series:
    invalid = out["ratio"] < INVALID_BELOW
    feed_missing = (out["other_usual"] > FEED_MATERIAL) & (out["other"] < FEED_MISSING_SHARE * out["other_usual"])
    tolerance = np.maximum(MISMATCH_ABS, MISMATCH_REL * out["total"].abs())
    mismatch = (out["other"] - out["other_usual"]).abs() > tolerance
    # no offtake data that day: fall back to the ratio rule
    no_offtake = out["offtake"].isna()
    suspect = no_offtake & (out["ratio"] < SUSPECT_BELOW)
    return pd.Series(np.select([invalid, suspect, feed_missing & ~no_offtake, mismatch & ~no_offtake],
                               ["invalid", "suspect", "missing_feed", "mismatch"], "ok"), index=out.index)


def _derive(out: pd.DataFrame) -> pd.DataFrame:
    ok_total = out["total"].where(out["flag"] == "ok")
    out["target"] = ok_total - out["dm"]
    out["target_repaired"] = out["total_repaired"] - out["dm"]
    out["gap"] = ok_total - out["dm"] - out["ndm"]
    out["residual"] = out["gap"] - out["uig"]
    return out


def _gb(ldz: pd.DataFrame) -> pd.DataFrame:
    """GB = sum of LDZs; a GB day takes the worst flag of its LDZs (a missing LDZ total counts as invalid)."""
    by_day = ldz.groupby(level="gas_day")
    cols = ["total", "dm", "ndm", "uig", "offtake", "other", "total_repaired"]
    gb = by_day[cols].sum(min_count=len(LDZS))
    gb["uig"] = gb["uig"].where(by_day["uig"].count() == len(LDZS))
    gb["total_repaired"] = gb["total_repaired"].where(by_day["total_repaired"].count() == len(LDZS))
    gb["cwv"] = gb["cv"] = gb["other_usual"] = np.nan
    gb["ratio"] = gb["total"] / (gb["dm"] + gb["ndm"])
    worst = by_day["flag"].max().astype(str).where(gb["total"].notna(), "invalid")
    gb["flag"] = pd.Categorical(worst, categories=FLAGS, ordered=True)
    gb = _derive(gb)
    gb.index = pd.MultiIndex.from_product([gb.index, [GB]], names=["gas_day", "ldz"])
    return gb


def flagged_days(energy: pd.DataFrame, pct: float = 5.0) -> pd.DataFrame:
    """LDZ-days with a flag, or a shrinkage residual beyond ±pct of total (UIG era only)."""
    e = energy.drop(index=GB, level="ldz")
    residual_pct = 100 * e["residual"] / e["total"]
    flagged = e[(e["flag"] != "ok") | (residual_pct.abs() > pct)].copy()
    flagged["residual_pct"] = residual_pct
    flagged["reason"] = np.where(flagged["flag"] != "ok", flagged["flag"].astype(str), f"residual > {pct:g}%")
    cols = ["reason", "ratio", "total", "offtake", "other", "other_usual", "total_repaired", "dm", "ndm", "uig"]
    return flagged[cols].round(2).reset_index().sort_values(["gas_day", "ldz"])


def target_summary(energy: pd.DataFrame) -> pd.DataFrame:
    """Per LDZ: gas days with a published total, flagged days by reason, and the days each target keeps."""
    e = energy.drop(index=GB, level="ldz")
    e = e[e["total"].notna()]
    g = e.groupby(level="ldz")
    out = pd.DataFrame({"days": g.size()})
    for f in FLAGS[1:]:
        out[f] = g["flag"].apply(lambda s, f=f: int((s == f).sum()))
    out["target_a"] = g["target"].count()
    out["target_b"] = g["target_repaired"].count()
    out["repaired"] = out["target_b"] - out["target_a"]
    return out[[c for c in out.columns if c in ("days", "target_a", "target_b", "repaired") or out[c].any()]]


def gas_year(days) -> np.ndarray:
    """Gas year (Oct-Sep) label for each day, e.g. '2025/26'."""
    days = pd.DatetimeIndex(days)
    start = np.where(days.month >= 10, days.year, days.year - 1)
    return np.array([f"{y}/{(y + 1) % 100:02d}" for y in start])
