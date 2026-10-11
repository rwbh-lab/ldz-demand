"""
Charts for the National Gas tables (ng_ldz_daily, ng_offtake_daily).

The data preparation (energy units, flags, targets) lives in ldz_demand.data.ldz_energy; these
functions only draw its output.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ldz_demand.charts.style import active
from ldz_demand.data.ingest.national_gas import ITEMS, LDZS
from ldz_demand.data.ldz_energy import GB, gas_year

ITEM_ORDER = list(ITEMS)
ITEM_LABELS = {
    "demand_total_d1": "Total D+1", "demand_total_d6": "Total D+6",
    "demand_dm_d1": "DM D+1", "demand_dm_d6": "DM D+6",
    "demand_ndm_d1": "NDM D+1", "demand_ndm_d6": "NDM D+6",
    "demand_uig_d1": "UIG D+1", "demand_uig_d6": "UIG D+6",
    "cv": "Calorific value", "cwv_actual": "CWV (actual)",
}


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
    if e["offtake"].notna().any():
        fig.add_trace(go.Scatter(x=e.index, y=e["offtake"], name="NTS offtakes", visible="legendonly",
                                 line=dict(width=1.5, color=t.muted), hovertemplate="%{y:,.1f} GWh"))
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
        fig.add_trace(go.Scatter(x=bad.index, y=np.zeros(len(bad)), mode="markers", name="Flagged day (excluded)",
                                 marker=dict(symbol="x", size=8, color=t.serious, line=dict(width=0)),
                                 customdata=np.stack([bad["flag"].astype(str), bad["ratio"]], axis=1),
                                 hovertemplate="%{customdata[0]} — total %{customdata[1]:.2f}× DM+NDM<extra></extra>"))
    fig.update_layout(title=f"What the published parts don't explain — {_label(ldz)}", yaxis_title=unit,
                      hovermode="x unified", height=400, xaxis=_range_controls())
    if as_pct:
        fig.update_yaxes(range=[-15, 25])
    return fig


def cwv_scatter(energy: pd.DataFrame, ldz: str, highlight: str | None = None, target: str = "target") -> go.Figure:
    """Official CWV vs the target (total − DM; `target` or `target_repaired`). Highlighted gas year in colour."""
    t = active()
    e = energy.xs(ldz, level="ldz").dropna(subset=["cwv", target]).rename(columns={target: "y"})
    year = gas_year(e.index)
    fig = go.Figure()
    others = e[year != highlight]
    fig.add_trace(go.Scattergl(x=others["cwv"], y=others["y"], mode="markers", name="Other gas years",
                               marker=dict(size=6, color=_alpha(t.muted, 0.45), line=dict(width=0)),
                               customdata=others.index.strftime("%d %b %Y"),
                               hovertemplate="%{customdata}<br>CWV %{x:.1f} → %{y:,.1f} GWh<extra></extra>"))
    if highlight:
        sel = e[year == highlight]
        fig.add_trace(go.Scattergl(x=sel["cwv"], y=sel["y"], mode="markers", name=f"Gas year {highlight}",
                                   marker=dict(size=8, color=t.series[0], line=dict(width=1, color=t.surface)),
                                   customdata=sel.index.strftime("%d %b %Y"),
                                   hovertemplate="%{customdata}<br>CWV %{x:.1f} → %{y:,.1f} GWh<extra></extra>"))
    fig.update_layout(title=f"Weather vs demand — {_label(ldz)}", xaxis_title="Official CWV (°C)",
                      yaxis_title="Total − DM (GWh / day)", height=460, hovermode="closest")
    return fig


def gas_years(energy: pd.DataFrame) -> list[str]:
    """Gas years (Oct–Sep) present, e.g. '2025/26', newest first."""
    return sorted(set(gas_year(energy.index.get_level_values("gas_day"))), reverse=True)


def offtake_share(energy: pd.DataFrame) -> go.Figure:
    """Per LDZ: NTS offtakes as % of the published total on ok days — median dot, 5–95% range bar."""
    t = active()
    e = energy.drop(index=GB, level="ldz")
    e = e[(e["flag"] == "ok") & e["offtake"].notna() & (e["total"] > 0)]
    share = (100 * e["offtake"] / e["total"]).groupby(level="ldz")
    stats = pd.DataFrame({"median": share.median(), "p05": share.quantile(0.05), "p95": share.quantile(0.95)})
    stats = stats.reindex([z for z in LDZS if z in stats.index][::-1])  # EA at the top
    fig = go.Figure()
    fig.add_vline(x=100, line=dict(color=t.axis, width=1))
    fig.add_trace(go.Scatter(
        x=stats["median"], y=stats.index, mode="markers", name="Median day",
        marker=dict(size=10, color=t.series[0], line=dict(width=2, color=t.surface)),
        error_x=dict(type="data", symmetric=False, array=stats["p95"] - stats["median"],
                     arrayminus=stats["median"] - stats["p05"], color=_alpha(t.series[0], 0.5), thickness=2, width=0),
        customdata=stats[["p05", "p95"]].values,
        hovertemplate="%{y}: median %{x:.1f}% (5–95%%: %{customdata[0]:.0f}–%{customdata[1]:.0f}%)<extra></extra>",
    ))
    fig.update_layout(title="NTS offtakes as a share of each LDZ's published total (ok days)",
                      xaxis_title="Offtakes ÷ total (%) — bar shows the 5–95% range of days",
                      height=440, showlegend=False, hovermode="closest",
                      yaxis=dict(showgrid=False))
    return fig


def feed_check(energy: pd.DataFrame, ldz: str) -> go.Figure:
    """Total − NTS offtakes (the LDZ's non-NTS input) against its usual level, with flagged days."""
    t = active()
    e = energy.xs(ldz, level="ldz")
    fig = go.Figure()
    fig.add_hline(y=0, line=dict(color=t.axis, width=1))
    fig.add_trace(go.Scatter(x=e.index, y=e["other"], name="Total − NTS offtakes",
                             line=dict(color=t.series[0], width=1.5), hovertemplate="%{y:,.1f} GWh"))
    usual = e["other_usual"].dropna()
    if len(usual):
        fig.add_hline(y=usual.iloc[0], line=dict(color=t.ink_2, width=1),
                      annotation_text=f"usual {usual.iloc[0]:.1f} GWh/day", annotation_position="top left",
                      annotation_font=dict(color=t.ink_2, size=12))
    for flag, symbol in (("missing_feed", "x"), ("mismatch", "circle-open"), ("invalid", "x-thin")):
        bad = e[e["flag"] == flag]
        if len(bad):
            fig.add_trace(go.Scatter(x=bad.index, y=bad["other"], mode="markers", name=flag.replace("_", " "),
                                     marker=dict(symbol=symbol, size=8, color=t.serious, line=dict(width=1.5, color=t.serious)),
                                     hovertemplate=f"{flag}: %{{y:,.1f}} GWh<extra></extra>"))
    # scale to the bulk of the data so a few extreme one-off days don't flatten the picture
    other = e["other"].dropna()
    if len(other):
        lo, hi = other.quantile([0.01, 0.99])
        top = max(hi, usual.iloc[0] if len(usual) else 0)
        fig.update_yaxes(range=[min(lo, 0) - 10, top + 10])
    fig.update_layout(title=f"Published total vs metered NTS offtakes — {_label(ldz)}",
                      yaxis_title="GWh / day (extremes off-scale; see table)",
                      hovermode="x unified", height=400, xaxis=_range_controls())
    return fig


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
