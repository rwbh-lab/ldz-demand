"""
Charts for the National Gas LDZ table (ng_ldz_daily).

energy_frame() puts every demand item into the same unit (GWh/day) and flags bad days; the chart
functions take its output. Total demand is published in mcm, so it is converted with the LDZ
calorific value: GWh = mcm * CV[MJ/m3] / 3.6.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ldz_demand.charts.style import active
from ldz_demand.data.ingest.national_gas import ITEMS, LDZS

GB = "GB"  # all 13 LDZs summed
# Data-quality flags on the published total, by its ratio to DM + NDM (normally ~1.0):
INVALID_BELOW = 0.1  # zero / negative / near-zero totals: clear publication errors
SUSPECT_BELOW = 0.7  # sustained low totals (e.g. SE 2022-23): part of the metered total likely missing
FLAGS = ("ok", "suspect", "invalid")

ITEM_ORDER = list(ITEMS)
ITEM_LABELS = {
    "demand_total_d1": "Total D+1", "demand_total_d6": "Total D+6",
    "demand_dm_d1": "DM D+1", "demand_dm_d6": "DM D+6",
    "demand_ndm_d1": "NDM D+1", "demand_ndm_d6": "NDM D+6",
    "demand_uig_d1": "UIG D+1", "demand_uig_d6": "UIG D+6",
    "cv": "Calorific value", "cwv_actual": "CWV (actual)",
}


def energy_frame(df: pd.DataFrame, closeout: str = "d6") -> pd.DataFrame:
    """
    Wide GWh/day frame indexed by (gas_day, ldz), plus GB totals.

    Columns: total, dm, ndm, uig (GWh/day), cwv (degC), cv (MJ/m3),
    target = total - dm, gap = total - dm - ndm (UIG + shrinkage),
    residual = gap - uig (shrinkage; from March 2025 when UIG exists),
    ratio = total / (dm + ndm), flag = ok | suspect | invalid (see SUSPECT_BELOW / INVALID_BELOW).
    Flagged days are excluded from target, gap and residual.
    """
    w = df.pivot_table(index=["gas_day", "ldz"], columns="item", values="value")
    out = pd.DataFrame(index=w.index)
    out["total"] = w[f"demand_total_{closeout}"] * w["cv"] / 3.6
    for part in ("dm", "ndm", "uig"):
        out[part] = w[f"demand_{part}_{closeout}"] / 1e6
    out["cwv"] = w["cwv_actual"]
    out["cv"] = w["cv"]
    out = _derive(out)

    gb = _gb(out)
    return pd.concat([out, gb]).sort_index()


def _derive(out: pd.DataFrame, flag: pd.Series | None = None) -> pd.DataFrame:
    out["ratio"] = out["total"] / (out["dm"] + out["ndm"])
    if flag is None:
        flag = pd.Series(np.select([out["ratio"] < INVALID_BELOW, out["ratio"] < SUSPECT_BELOW],
                                   ["invalid", "suspect"], "ok"), index=out.index)
    out["flag"] = pd.Categorical(flag, categories=FLAGS, ordered=True)
    total = out["total"].where(out["flag"] == "ok")
    out["target"] = total - out["dm"]
    out["gap"] = total - out["dm"] - out["ndm"]
    out["residual"] = out["gap"] - out["uig"]
    return out


def _gb(ldz: pd.DataFrame) -> pd.DataFrame:
    """GB = sum of LDZs; a day takes the worst flag of its LDZs (missing totals count as invalid)."""
    by_day = ldz.groupby(level="gas_day")
    gb = by_day[["total", "dm", "ndm", "uig"]].sum(min_count=len(LDZS)).assign(cwv=np.nan, cv=np.nan)
    gb["uig"] = gb["uig"].where(by_day["uig"].count() == len(LDZS))
    worst = by_day["flag"].max().astype(str).where(gb["total"].notna(), "invalid")
    gb = _derive(gb, flag=worst)
    gb.index = pd.MultiIndex.from_product([gb.index, [GB]], names=["gas_day", "ldz"])
    return gb


def flagged_days(energy: pd.DataFrame, pct: float = 5.0) -> pd.DataFrame:
    """LDZ-days flagged suspect / invalid, or with a shrinkage residual beyond ±pct of total."""
    e = energy.drop(index=GB, level="ldz")
    residual_pct = 100 * e["residual"] / e["total"]
    flagged = e[(e["flag"] != "ok") | (residual_pct.abs() > pct)].copy()
    flagged["residual_pct"] = residual_pct
    flagged["reason"] = np.where(flagged["flag"] != "ok", flagged["flag"].astype(str) + " total", f"residual > {pct:g}%")
    cols = ["reason", "ratio", "total", "dm", "ndm", "uig", "residual", "residual_pct"]
    return flagged[cols].round(2).reset_index().sort_values(["gas_day", "ldz"])


# --- charts ------------------------------------------------------------------------------------

def coverage(df: pd.DataFrame) -> go.Figure:
    """Heatmap: for each item and gas day, how many of the 13 LDZs have a value."""
    t = active()
    counts = (
        df[df["value"].notna()].groupby(["item", "gas_day"])["ldz"].nunique()
        .unstack("gas_day").reindex(ITEM_ORDER[::-1])
    )
    # one hue, receding to the surface at zero; full coverage is a calm mid blue, so gaps stand out
    fig = go.Figure(go.Heatmap(
        z=counts.values, x=counts.columns, y=[ITEM_LABELS[i] for i in counts.index], zmin=0, zmax=len(LDZS),
        colorscale=[[0, t.surface], [0.5, t.sequential[1]], [1, t.series[0]]],
        colorbar=dict(title=dict(text="LDZs"), tickvals=[0, 13], outlinewidth=0, thickness=10),
        hovertemplate="%{y}<br>%{x|%d %b %Y}: %{z} of 13 LDZs<extra></extra>",
        xgap=0, ygap=3,
    ))
    fig.update_layout(title="Data coverage — LDZs reporting each item", height=360,
                      yaxis=dict(showgrid=False, showline=False, ticks=""), xaxis=dict(showgrid=False))
    return fig


def composition(energy: pd.DataFrame, ldz: str) -> go.Figure:
    """Stacked DM + NDM with the measured total on top; the space between is UIG + shrinkage."""
    t = active()
    e = energy.xs(ldz, level="ldz")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=e.index, y=e["dm"], name="Daily metered (DM)", stackgroup="parts",
                             line=dict(width=0.5, color=t.series[0]), fillcolor=_alpha(t.series[0], 0.75),
                             hovertemplate="%{y:,.1f} GWh"))
    fig.add_trace(go.Scatter(x=e.index, y=e["ndm"], name="Non-daily metered (NDM)", stackgroup="parts",
                             line=dict(width=0.5, color=t.series[1]), fillcolor=_alpha(t.series[1], 0.75),
                             hovertemplate="%{y:,.1f} GWh"))
    fig.add_trace(go.Scatter(x=e.index, y=e["total"], name="Total (metered, as published)",
                             line=dict(width=1.5, color=t.ink), hovertemplate="%{y:,.1f} GWh"))
    fig.update_layout(title=f"Demand composition — {_label(ldz)}", yaxis_title="GWh / day",
                      hovermode="x unified", height=420, xaxis=_range_controls())
    return fig


def gap(energy: pd.DataFrame, ldz: str, as_pct: bool = False) -> go.Figure:
    """Total minus the published parts: UIG + shrinkage (full history), and shrinkage alone (UIG era)."""
    t = active()
    e = energy.xs(ldz, level="ldz")
    scale = 100 / e["total"] if as_pct else 1
    unit = "% of total" if as_pct else "GWh / day"
    fig = go.Figure()
    fig.add_hline(y=0, line=dict(color=t.axis, width=1))
    fig.add_trace(go.Scatter(x=e.index, y=e["gap"] * scale, name="Total − DM − NDM  (UIG + shrinkage)",
                             line=dict(color=t.series[0], width=1.5), hovertemplate="%{y:,.2f}"))
    fig.add_trace(go.Scatter(x=e.index, y=e["residual"] * scale, name="… − UIG  (shrinkage, from Mar 2025)",
                             line=dict(color=t.series[1], width=1.5), hovertemplate="%{y:,.2f}"))
    bad = e[e["flag"] != "ok"]
    if len(bad):
        fig.add_trace(go.Scatter(x=bad.index, y=np.zeros(len(bad)), mode="markers", name="Flagged total (excluded)",
                                 marker=dict(symbol="x", size=8, color=t.serious, line=dict(width=0)),
                                 customdata=np.stack([bad["flag"].astype(str), bad["ratio"]], axis=1),
                                 hovertemplate="%{customdata[0]} total — %{customdata[1]:.2f}× DM+NDM<extra></extra>"))
    fig.update_layout(title=f"What the published parts don't explain — {_label(ldz)}", yaxis_title=unit,
                      hovermode="x unified", height=400, xaxis=_range_controls())
    if as_pct:
        fig.update_yaxes(range=[-15, 25])
    return fig


def cwv_scatter(energy: pd.DataFrame, ldz: str, highlight: str | None = None) -> go.Figure:
    """Official CWV vs the target (total − DM). Highlighted gas year in colour, others muted."""
    t = active()
    e = energy.xs(ldz, level="ldz").dropna(subset=["cwv", "target"])
    year = _gas_year(e.index)
    fig = go.Figure()
    others = e[year != highlight]
    fig.add_trace(go.Scattergl(x=others["cwv"], y=others["target"], mode="markers", name="Other gas years",
                               marker=dict(size=6, color=_alpha(t.muted, 0.45), line=dict(width=0)),
                               customdata=others.index.strftime("%d %b %Y"),
                               hovertemplate="%{customdata}<br>CWV %{x:.1f} → %{y:,.1f} GWh<extra></extra>"))
    if highlight:
        sel = e[year == highlight]
        fig.add_trace(go.Scattergl(x=sel["cwv"], y=sel["target"], mode="markers", name=f"Gas year {highlight}",
                                   marker=dict(size=8, color=t.series[0], line=dict(width=1, color=t.surface)),
                                   customdata=sel.index.strftime("%d %b %Y"),
                                   hovertemplate="%{customdata}<br>CWV %{x:.1f} → %{y:,.1f} GWh<extra></extra>"))
    fig.update_layout(title=f"Weather vs demand — {_label(ldz)}", xaxis_title="Official CWV (°C)",
                      yaxis_title="Total − DM (GWh / day)", height=460, hovermode="closest")
    return fig


def gas_years(energy: pd.DataFrame) -> list[str]:
    """Gas years (Oct–Sep) present, e.g. '2025/26', newest first."""
    return sorted(set(_gas_year(energy.index.get_level_values("gas_day"))), reverse=True)


def _gas_year(days) -> np.ndarray:
    days = pd.DatetimeIndex(days)
    start = np.where(days.month >= 10, days.year, days.year - 1)
    return np.array([f"{y}/{(y + 1) % 100:02d}" for y in start])


def _label(ldz: str) -> str:
    return "GB (all 13 LDZs)" if ldz == GB else f"LDZ {ldz}"


def _range_controls() -> dict:
    t = active()
    return dict(
        rangeselector=dict(
            buttons=[dict(count=1, label="1y", step="year", stepmode="backward"),
                     dict(count=2, label="2y", step="year", stepmode="backward"),
                     dict(step="all", label="All")],
            bgcolor=t.surface, activecolor=t.axis, bordercolor=t.axis, borderwidth=1,
            font=dict(color=t.ink_2), x=0, y=1.0, yanchor="bottom",
        ),
    )


def _alpha(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"
