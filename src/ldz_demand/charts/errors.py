"""
Charts for the Error analysis page: coverage by lead day, the median's bias, where demand lands among the
percentiles (PIT), and where ERA5's weather lands among the members (rank histogram, spread against error).
"""

import pandas as pd
import plotly.graph_objects as go

from ldz_demand.charts.forecasts import _alpha
from ldz_demand.charts.pages import P, P_RANGE
from ldz_demand.charts.style import active


def _bars_against_expected(labels, observed, expected, title: str, xaxis: str, hover: str) -> go.Figure:
    t = active()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=observed * 100, name="Observed", marker_color=t.series[0],
                         hovertemplate="%{x}: %{y:.0f}%<extra>" + hover + "</extra>"))
    fig.add_trace(go.Scatter(x=labels, y=expected * 100, name="If calibrated", mode="markers",
                             marker=dict(symbol="line-ew", size=34, line=dict(color=t.ink, width=2.5)),
                             hovertemplate="%{x}: %{y:.0f}%<extra>if calibrated</extra>"))
    fig.update_layout(title=title, xaxis_title=xaxis, yaxis_title="Share of days (%)", height=380, bargap=0.25,
                      legend=dict(orientation="h", y=-0.22, yanchor="top", x=0, xanchor="left"))
    return fig


def coverage_by_lead(by_lead: pd.DataFrame, title: str) -> go.Figure:
    """Share inside P10–P90 per lead day, the blend and the weather alone, each with its exact 95% interval,
    against the 80% target."""
    t = active()
    fig = go.Figure()
    for name, col, colour, dash in (("With model error (the published range)", "blend", t.series[0], "solid"),
                                    ("Weather only", "weather", t.ink_2, "dot")):
        x = by_lead["lead_days"]
        fig.add_trace(go.Scatter(x=list(x) + list(x[::-1]),
                                 y=list(by_lead[f"{col}_hi"] * 100) + list(by_lead[f"{col}_lo"][::-1] * 100),
                                 fill="toself", fillcolor=_alpha(colour, 0.14), line=dict(width=0), hoverinfo="skip",
                                 showlegend=False, legendgroup=col))
        fig.add_trace(go.Scatter(x=x, y=by_lead[col] * 100, name=name, legendgroup=col, mode="lines+markers",
                                 line=dict(color=colour, width=2, dash=dash),
                                 customdata=by_lead[[f"{col}_inside", "n"]].to_numpy(),
                                 hovertemplate="lead %{x}: %{y:.0f}% (%{customdata[0]} of %{customdata[1]})<extra>"
                                               + name + "</extra>"))
    fig.add_hline(y=80, line=dict(color=t.muted, width=1, dash="dash"), annotation_text="target 80%",
                  annotation_position="bottom right", annotation_font_color=t.muted)
    fig.update_layout(title=title, xaxis_title="Lead day (0: the gas day the run is issued)",
                      yaxis_title=f"Inside {P_RANGE} (%)", yaxis_range=[0, 105], height=420, hovermode="x unified",
                      legend=dict(orientation="h", y=-0.2, yanchor="top", x=0, xanchor="left"))
    return fig


def bias_by_lead(bias: pd.DataFrame, title: str) -> go.Figure:
    """The median forecast's mean error per lead day, % of demand (positive: too high)."""
    t = active()
    fig = go.Figure()
    text = [f"lead {d}: mean {m:+.1f}%, median {md:+.1f}% ({n} days)"  # signs in Python: Plotly.js drops '+'
            for d, m, md, n in bias[["lead_days", "mean", "median", "n"]].itertuples(index=False)]
    fig.add_trace(go.Bar(x=bias["lead_days"], y=bias["mean"],
                         marker_color=[t.diverging[-2] if m > 0 else t.diverging[1] for m in bias["mean"]],
                         hovertext=text, hoverinfo="text", name="Mean error"))
    fig.add_hline(y=0, line=dict(color=t.axis, width=1))
    fig.update_layout(title=title, xaxis_title="Lead day", yaxis_title=f"Median {P(50)} − actual (% of demand)",
                      height=360, showlegend=False)
    return fig


def pit(p: pd.DataFrame, title: str) -> go.Figure:
    """Where the actual fell among the stored percentiles, against the band widths."""
    return _bars_against_expected(p["band"], p["observed"], p["expected"], title,
                                  "Where the actual fell in the forecast", "observed")


def rank_histogram(h: pd.DataFrame, title: str) -> go.Figure:
    """ERA5's rank among the members, in bins, against the flat histogram of a calibrated ensemble."""
    n = len(h)
    labels = ["coldest"] + [f"{i + 1}" for i in range(1, n - 1)] + ["warmest"]
    labels = [f"{i * 10}–{(i + 1) * 10}%" for i in range(n)] if n == 10 else labels
    return _bars_against_expected(labels, h["observed"], h["expected"], title,
                                  "ERA5's place among the 50 members (0%: below them all; 100%: above them all)",
                                  "observed")


def spread_skill(ss: pd.DataFrame, title: str, unit: str) -> go.Figure:
    """Per lead day: the members' spread against the error of their mean, and the bias."""
    t = active()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ss["lead_days"], y=ss["rmse"], name="Error of the members' mean (RMSE)",
                             mode="lines+markers", line=dict(color=t.series[1], width=2),
                             hovertemplate="lead %{x}: %{y:.2f} " + unit + "<extra>RMSE</extra>"))
    fig.add_trace(go.Scatter(x=ss["lead_days"], y=ss["spread"], name="Members' spread (SD)", mode="lines+markers",
                             line=dict(color=t.series[0], width=2),
                             hovertemplate="lead %{x}: %{y:.2f} " + unit + "<extra>spread</extra>"))
    fig.add_trace(go.Bar(x=ss["lead_days"], y=ss["bias"], name="Bias (members' mean − ERA5)", opacity=0.45,
                         marker_color=t.muted, customdata=[f"{b:+.2f}" for b in ss["bias"]],
                         hovertemplate="lead %{x}: %{customdata} " + unit + "<extra>bias</extra>"))
    fig.add_hline(y=0, line=dict(color=t.axis, width=1))
    fig.update_layout(title=title, xaxis_title="Lead day", yaxis_title=unit, height=400, hovermode="x unified",
                      legend=dict(orientation="h", y=-0.2, yanchor="top", x=0, xanchor="left"))
    return fig
