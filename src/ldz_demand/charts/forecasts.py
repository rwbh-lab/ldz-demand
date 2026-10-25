"""
Charts for the Live forecasts page: the fan for one run, how the forecast for each day moved from run
to run, and how forecasts verify against demand as it is published.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ldz_demand.charts.style import active


def _alpha(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def wide(runs: pd.DataFrame) -> pd.DataFrame:
    """statistics rows -> one row per run, LDZ and gas day."""
    return runs.pivot_table(index=["run_date", "ldz", "gas_day", "lead_days"], columns="statistic",
                            values="value").reset_index()


def fan(run: pd.DataFrame, actual: pd.DataFrame, ldz: str) -> go.Figure:
    """One run's forecast for one LDZ: P05–P95, P10–P90, P25–P75 bands, median, weather-only band, actuals."""
    t = active()
    f = run[run["ldz"] == ldz].sort_values("gas_day")
    x = list(f["gas_day"]) + list(f["gas_day"][::-1])
    fig = go.Figure()
    for lo, hi, alpha, name in (("p05", "p95", 0.12, "5–95%"), ("p10", "p90", 0.22, "10–90%"),
                                ("p25", "p75", 0.38, "25–75%")):
        fig.add_trace(go.Scatter(x=x, y=list(f[hi]) + list(f[lo][::-1]), fill="toself", name=name,
                                 fillcolor=_alpha(t.series[0], alpha), line=dict(width=0), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=f["gas_day"], y=f["p50"], name="Median", line=dict(color=t.series[0], width=2.5),
                             customdata=np.stack([f["p10"], f["p90"]], axis=1),
                             hovertemplate="%{x|%a %d %b}: %{y:,.0f} GWh (10–90%: %{customdata[0]:,.0f}–%{customdata[1]:,.0f})"
                                           "<extra>forecast</extra>"))
    for col in ("weather_p10", "weather_p90"):
        fig.add_trace(go.Scatter(x=f["gas_day"], y=f[col], mode="lines", name="Weather only, 10–90%", showlegend=col == "weather_p10",
                                 legendgroup="weather", line=dict(color=t.ink_2, width=1, dash="dot"),
                                 hovertemplate="%{x|%a %d %b}: %{y:,.0f} GWh<extra>weather only</extra>"))
    a = actual[(actual["ldz"] == ldz) & actual["gas_day"].isin(f["gas_day"])]
    if not a.empty:
        fig.add_trace(go.Scatter(x=a["gas_day"], y=a["actual"], mode="markers", name="Actual",
                                 marker=dict(size=9, color=t.ink, symbol=np.where(a["provisional"], "circle-open", "circle")),
                                 customdata=np.where(a["provisional"], "provisional (D+1)", "closed out (D+6)"),
                                 hovertemplate="%{x|%a %d %b}: %{y:,.0f} GWh, %{customdata}<extra>actual</extra>"))
    run_date = pd.Timestamp(f["run_date"].iloc[0])
    fig.update_layout(title=f"Demand forecast, {ldz} — 00z run of {run_date:%a %d %b %Y}",
                      yaxis_title="Total − DM (GWh / day)", height=440, hovermode="x unified")
    return fig


def runs_compared(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str) -> go.Figure:
    """Each run's median and 10–90% for one LDZ: how the forecast for each day moved as the day approached."""
    t = active()
    w = runs[runs["ldz"] == ldz]
    fig = go.Figure()
    dates = sorted(w["run_date"].unique())
    for i, rd in enumerate(dates):
        f = w[w["run_date"] == rd].sort_values("gas_day")
        colour = t.series[i % len(t.series)]
        fig.add_trace(go.Scatter(x=f["gas_day"], y=f["p50"], name=f"{pd.Timestamp(rd):%d %b} run",
                                 line=dict(color=colour, width=2), customdata=np.stack([f["p10"], f["p90"]], axis=1),
                                 hovertemplate="%{x|%d %b}: %{y:,.0f} (10–90%: %{customdata[0]:,.0f}–%{customdata[1]:,.0f})"))
    a = actual[(actual["ldz"] == ldz) & (actual["gas_day"] >= w["gas_day"].min())]
    if not a.empty:
        fig.add_trace(go.Scatter(x=a["gas_day"], y=a["actual"], mode="markers", name="Actual",
                                 marker=dict(size=9, color=t.ink), hovertemplate="%{x|%d %b}: %{y:,.0f} GWh<extra>actual</extra>"))
    fig.update_layout(title=f"Medians by run, {ldz}", yaxis_title="Total − DM (GWh / day)", height=380,
                      hovermode="x unified")
    return fig


def verification(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str) -> pd.DataFrame:
    """Every forecast day with an actual: error of the median, and where the actual fell in the interval."""
    w = runs[runs["ldz"] == ldz].merge(actual[actual["ldz"] == ldz], on=["gas_day", "ldz"])
    if w.empty:
        return w
    w["error %"] = (w["p50"] - w["actual"]) / w["actual"] * 100
    w["in 10–90%"] = (w["actual"] >= w["p10"]) & (w["actual"] <= w["p90"])
    w["in weather-only 10–90%"] = (w["actual"] >= w["weather_p10"]) & (w["actual"] <= w["weather_p90"])
    out = w[["run_date", "gas_day", "lead_days", "actual", "p50", "p10", "p90", "error %", "in 10–90%",
             "in weather-only 10–90%", "provisional"]].sort_values(["gas_day", "run_date"])
    return out
