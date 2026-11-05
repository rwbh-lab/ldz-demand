"""
Charts for the Live forecasts page: the fan for one run, how the forecast for each day moved from run
to run, and how forecasts verify against demand as it is published.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ldz_demand.charts.pages import P, P_RANGE, Q, Q_at
from ldz_demand.charts.style import active

YAXIS = f"{Q}, total − DM (GWh/day)"


def _alpha(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def wide(runs: pd.DataFrame) -> pd.DataFrame:
    """statistics rows -> one row per run, LDZ and gas day."""
    return runs.pivot_table(index=["run_date", "ldz", "gas_day", "lead_days"], columns="statistic",
                            values="value").reset_index()


def add_actuals(fig: go.Figure, a: pd.DataFrame, name: str = "Published") -> None:
    """Published demand as a vertical bar, the figure's 10-90% range, with a short tick at the value (lo, hi from
    forecast.actuals(): the usual D+1 -> D+6 revision for provisional figures, the metering tolerance once
    closed out). Provisional figures are drawn fainter."""
    t = active()
    if a.empty:
        return
    a = a.sort_values("gas_day")
    has_range = {"lo", "hi"} <= set(a.columns)
    for prov, label, opacity in ((False, f"{name} {Q_at(6)} (closed out)", 1.0), (True, f"{name} {Q_at(1)} (provisional)", 0.55)):
        part = a[a["provisional"] == prov]
        if part.empty:
            continue
        xs, ys = [], []
        if has_range:
            for r in part.itertuples():
                xs += [r.gas_day, r.gas_day, None]
                ys += [r.lo, r.hi, None]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", legendgroup=label, showlegend=False, opacity=opacity,
                                     line=dict(color=t.ink, width=2), hoverinfo="skip"))
        lo = part["lo"] if has_range else part["actual"]
        hi = part["hi"] if has_range else part["actual"]
        fig.add_trace(go.Scatter(x=part["gas_day"], y=part["actual"], mode="markers", name=label, legendgroup=label,
                                 # a short tick across the bar marks the value itself
                                 marker=dict(symbol="line-ew", size=8, line=dict(width=2, color=t.ink)), opacity=opacity,
                                 customdata=np.stack([lo, hi], axis=1),
                                 hovertemplate="%{x|%a %d %b}: %{y:,.0f} GWh (" + P_RANGE + ": %{customdata[0]:,.0f}–%{customdata[1]:,.0f})"
                                               f"<extra>{'provisional' if prov else 'closed out'}</extra>"))


def run_age_legend(fig: go.Figure, dates: list, ramp: list) -> None:
    """One colour strip for the runs, oldest to newest, in place of a legend entry per run. The strip uses
    the same part of the ramp as the lines (0.2 for the oldest run to 1.0 for the newest)."""
    from plotly.colors import sample_colorscale

    first, last = pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])
    steps = np.linspace(0, 1, 11)
    scale = [[float(x), c] for x, c in zip(steps, sample_colorscale(ramp, list(0.2 + 0.8 * steps)))]
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers", showlegend=False, hoverinfo="skip",
        marker=dict(colorscale=scale, cmin=0, cmax=1, color=[0], showscale=True,
                    colorbar=dict(orientation="h", x=1, xanchor="right", y=1.02, yanchor="bottom", len=0.4,
                                  thickness=10, outlinewidth=0, tickvals=[0, 1],
                                  ticktext=[f"{first:%d %b} run", f"{last:%d %b} run"]))))
    # the strip takes the legend's place at the top right; the remaining entries (the actuals) go below
    fig.update_layout(legend=dict(orientation="h", y=-0.1, yanchor="top", x=0, xanchor="left"))


ANCHOR_DAYS = 3  # the fan starts from the latest published actual up to this many days before the run


def fan(run: pd.DataFrame, actual: pd.DataFrame, ldz: str, takeaway: str | None = None) -> go.Figure:
    """One run's forecast for one LDZ: P05–P95, P10–P90, P25–P75 bands, median, weather-only band, actuals.
    The bands and lines start from the latest published actual before the run (normally yesterday's
    provisional figure), so the range visibly fans out from a known point. takeaway: a title that says what
    the chart shows; the usual label then becomes its subtitle. The legend sits below the plot, so it never
    crowds the title on a narrow screen."""
    t = active()
    f = run[run["ldz"] == ldz].sort_values("gas_day")
    run_date = pd.Timestamp(f["run_date"].iloc[0])
    known = actual[(actual["ldz"] == ldz) & (actual["gas_day"] < run_date)
                   & (actual["gas_day"] >= run_date - pd.Timedelta(days=ANCHOR_DAYS))]
    cols = ["p05", "p95", "p10", "p90", "p25", "p75", "p50", "weather_p10", "weather_p90"]
    if known.empty:
        drawn = f
    else:
        anchor = known.sort_values("gas_day").iloc[-1]
        drawn = pd.concat([pd.DataFrame([{"gas_day": anchor["gas_day"], **{c: anchor["actual"] for c in cols}}]),
                           f[["gas_day", *cols]]], ignore_index=True)
    x = list(drawn["gas_day"]) + list(drawn["gas_day"][::-1])
    fig = go.Figure()
    for lo, hi, alpha, name in (("p05", "p95", 0.12, f"{P(5)}–{P(95)}"), ("p10", "p90", 0.22, P_RANGE),
                                ("p25", "p75", 0.38, f"{P(25)}–{P(75)}")):
        fig.add_trace(go.Scatter(x=x, y=list(drawn[hi]) + list(drawn[lo][::-1]), fill="toself", name=name,
                                 fillcolor=_alpha(t.series[0], alpha), line=dict(width=0), hoverinfo="skip"))
    # the lines are drawn from the anchor, but hover only on forecast days (the anchor is the actual's)
    fig.add_trace(go.Scatter(x=drawn["gas_day"][:2], y=drawn["p50"][:2], line=dict(color=t.series[0], width=2.5),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=f["gas_day"], y=f["p50"], name=f"Median, {P(50)}", line=dict(color=t.series[0], width=2.5),
                             customdata=np.stack([f["p10"], f["p90"]], axis=1),
                             hovertemplate="%{x|%a %d %b}: %{y:,.0f} GWh (" + P_RANGE + ": %{customdata[0]:,.0f}–%{customdata[1]:,.0f})"
                                           "<extra>forecast</extra>"))
    for col in ("weather_p10", "weather_p90"):
        fig.add_trace(go.Scatter(x=drawn["gas_day"][:2], y=drawn[col][:2], line=dict(color=t.ink_2, width=1, dash="dot"),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=f["gas_day"], y=f[col], mode="lines", name=f"Weather only, {P_RANGE}", showlegend=col == "weather_p10",
                                 legendgroup="weather", line=dict(color=t.ink_2, width=1, dash="dot"),
                                 hovertemplate="%{x|%a %d %b}: %{y:,.0f} GWh<extra>weather only</extra>"))
    add_actuals(fig, actual[(actual["ldz"] == ldz) & actual["gas_day"].isin(drawn["gas_day"])])
    label = f"{ldz} demand {Q} · 00z run of {run_date:%a %d %b %Y}"  # short, so it fits on a phone
    title = label if takeaway is None else dict(text=takeaway, subtitle=dict(text=label))
    fig.update_layout(title=title, yaxis_title=YAXIS, height=460, hovermode="x unified",
                      legend=dict(orientation="h", y=-0.12, yanchor="top", x=0, xanchor="left"),
                      margin=dict(t=88 if takeaway else 56))
    return fig


def runs_compared(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str) -> go.Figure:
    """Each run's median and 10–90% for one LDZ: how the forecast for each day moved as the day approached.
    Age is shown by colour and fade: the newest run is the brightest and thickest, older runs recede."""
    from plotly.colors import sample_colorscale

    t = active()
    w = runs[runs["ldz"] == ldz]
    fig = go.Figure()
    dates = sorted(w["run_date"].unique())
    n = len(dates)
    # the sequential ramp's last colour has the most contrast with the page, in dark and light themes alike
    ramp = [[i / (len(t.sequential) - 1), c] for i, c in enumerate(t.sequential)]
    for i, rd in enumerate(dates):
        f = w[w["run_date"] == rd].sort_values("gas_day")
        age = (n - 1 - i) / max(n - 1, 1)                     # 0 = newest, 1 = oldest
        newest = i == n - 1
        colour = sample_colorscale(ramp, [0.2 + 0.8 * (1 - age)])[0]
        fig.add_trace(go.Scatter(x=f["gas_day"], y=f["p50"], name=f"{pd.Timestamp(rd):%d %b} run", showlegend=False,
                                 line=dict(color=colour, width=3 if newest else 1.5), opacity=1.0 - 0.6 * age,
                                 customdata=np.stack([f["p10"], f["p90"]], axis=1),
                                 hovertemplate="%{x|%d %b}: %{y:,.0f} (" + P_RANGE + ": %{customdata[0]:,.0f}–%{customdata[1]:,.0f})"))
    run_age_legend(fig, dates, ramp)
    add_actuals(fig, actual[(actual["ldz"] == ldz) & (actual["gas_day"] >= w["gas_day"].min())])
    fig.update_layout(title=f"Medians by run, {ldz}", yaxis_title=YAXIS, height=560,
                      hovermode="x unified")
    return fig


def closed_out(actual: pd.DataFrame) -> pd.DataFrame:
    """Only the actuals National Gas has closed out (D+6). Scores use these alone: the provisional D+1
    figure can be far off for some LDZs (WS's D+1 DM is often incomplete), and GB inherits it."""
    return actual[~actual["provisional"]]


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
