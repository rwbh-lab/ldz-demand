"""
Charts for the Demand model page: each part of the CWV and the demand model, shown with the final fit
(ldz_demand.models.fit) for one LDZ. They explain what each part does, not how well the model scores
(that's the results).
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ldz_demand.charts.style import active
from ldz_demand.models import averaging, cwv, demand

KNOT = cwv.KNOT
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _alpha(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _window(frame: pd.DataFrame, months: int = 6) -> pd.DataFrame:
    """The latest complete October – March (or the last `months` months)."""
    last = frame["t2m"].last_valid_index()
    year = last.year if last.month >= 4 else last.year - 1
    start, end = pd.Timestamp(f"{year - 1}-10-01"), pd.Timestamp(f"{year}-03-31")
    out = frame.loc[start:end]
    return out if len(out) > 60 else frame.iloc[-months * 30:]


def heating_profile() -> go.Figure:
    """The weight of each UK local hour in the gas-day temperature."""
    t = active()
    hours = np.arange(24)
    w = averaging.hour_weights(hours, "peaks")
    order = (hours + 5) % 24  # the gas day runs 05:00 to 05:00
    fig = go.Figure(go.Bar(x=[f"{h:02d}:00" for h in order], y=w[order], marker=dict(color=t.series[0]),
                           hovertemplate="%{x}: weight %{y:.1f}<extra></extra>"))
    fig.add_hline(y=1, line=dict(color=t.muted, width=1, dash="dot"))
    fig.update_layout(title="Weight of each hour in the gas day's temperature", yaxis_title="Weight",
                      xaxis_title="UK local time (gas day 05:00 – 05:00)", height=300, bargap=0.15, showlegend=False)
    return fig


def gas_day_temperature(frame: pd.DataFrame) -> go.Figure:
    """The flat and heating-hours gas-day temperature through the latest winter."""
    t = active()
    w = _window(frame)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=w.index, y=w["t2m_flat"], name="Flat mean", line=dict(color=t.muted, width=1.5),
                             hovertemplate="%{x|%d %b %Y}: %{y:.1f} °C"))
    fig.add_trace(go.Scatter(x=w.index, y=w["t2m"], name="Heating hours", line=dict(color=t.series[0], width=2),
                             hovertemplate="%{x|%d %b %Y}: %{y:.1f} °C"))
    fig.update_layout(title="Gas-day temperature: flat mean vs heating hours", yaxis_title="°C", height=340,
                      hovermode="x unified")
    return fig


def effective_temperature(frame: pd.DataFrame, y_fit: float, y_try: float) -> go.Figure:
    """The day's temperature and the effective temperature E for the fitted y and a chosen y."""
    t = active()
    w = _window(frame)
    full = frame["t2m"].ffill()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=w.index, y=w["t2m"], name="Gas-day temperature", line=dict(color=t.muted, width=1),
                             hovertemplate="%{x|%d %b}: %{y:.1f} °C"))
    for y, name, colour, dash in ((y_fit, f"E, fitted y = {y_fit:.2f}", t.series[0], None),
                                  (y_try, f"E, y = {y_try:.2f}", t.series[1], "dash")):
        e = pd.Series(demand.effective_temperature(full.to_numpy(), y), index=frame.index).loc[w.index]
        fig.add_trace(go.Scatter(x=w.index, y=e, name=name, line=dict(color=colour, width=2, dash=dash),
                                 hovertemplate="%{x|%d %b}: %{y:.1f} °C"))
    fig.update_layout(title="Effective temperature: how many days the model remembers", yaxis_title="°C", height=360,
                      hovermode="x unified")
    return fig


def wind_chill(p: cwv.CWVParams) -> go.Figure:
    """How much colder wind makes the day count, by wind speed, at a few temperatures."""
    t = active()
    wind = np.linspace(0, 15, 61)
    fig = go.Figure()
    for i, temp in enumerate((0, 5, 10)):
        chill = p.I2 * np.maximum(0, wind - p.W0) * max(0.0, p.T0 - temp)
        fig.add_trace(go.Scatter(x=wind, y=-chill, name=f"{temp} °C", line=dict(color=t.series[i], width=2),
                                 hovertemplate=f"{temp} °C, wind %{{x:.1f}} m/s: %{{y:.2f}} °C<extra></extra>"))
    fig.update_layout(title="Wind chill: the change in CW", xaxis_title="Gas-day mean wind speed (m/s)",
                      yaxis_title="Change in CW (°C)", height=340)
    return fig


def solar(p: cwv.CWVParams, frame: pd.DataFrame) -> go.Figure:
    """The solar term S0 · SR by month (mean over the record), in CW °C."""
    t = active()
    s = (p.S0 * frame["ssrd"]).groupby(frame.index.month).mean().reindex(range(1, 13))
    fig = go.Figure(go.Bar(x=MONTHS, y=s, marker=dict(color=t.series[3]),
                           hovertemplate="%{x}: %{y:.2f} °C<extra></extra>"))
    fig.update_layout(title="Solar: the average lift in CW by month", yaxis_title="Change in CW (°C)", height=300,
                      showlegend=False)
    return fig


def seasonal_shape(fits: dict[str, demand.Fit], ldz: str) -> go.Figure:
    """Sc · g through the year: the shared shape, sized for each LDZ (this one highlighted)."""
    t = active()
    days = pd.date_range("2025-01-01", "2025-12-31")
    g = demand.calendar_shape(days, fits[ldz].shape)
    fig = go.Figure()
    for other, f in fits.items():
        if other != ldz:
            fig.add_trace(go.Scatter(x=days, y=f.params.Sc * g, name=other, line=dict(color=_alpha(t.muted, 0.5), width=1),
                                     showlegend=False, hovertemplate=f"{other} %{{x|%d %b}}: %{{y:.2f}} °C<extra></extra>"))
    fig.add_trace(go.Scatter(x=days, y=fits[ldz].params.Sc * g, name=ldz, line=dict(color=t.series[0], width=2.5),
                             hovertemplate=f"{ldz} %{{x|%d %b}}: %{{y:.2f}} °C<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=t.axis, width=1))
    fig.update_layout(title="Seasonal shape: the change in CW through the year", yaxis_title="Change in CW (°C)",
                      xaxis=dict(tickformat="%b"), height=340, showlegend=False)
    return fig


def transform(p: cwv.CWVParams, ldz: str, frame: pd.DataFrame | None = None, fit: demand.Fit | None = None) -> go.Figure:
    """CW -> CWV: ours against the published curve, with the regions marked; the LDZ's days as a rug."""
    t = active()
    pub = cwv.PUBLISHED[ldz]
    published = cwv.CWVParams(y=pub["y"], I2=0, W0=0, T0=0, S0=0, V0=pub["V0"], I3=pub["I3"], V1=pub["V1"],
                              dV=pub["V2"] - pub["V1"], q=pub["q"])
    days_cw = cw_series(fit, frame) if frame is not None and fit is not None else np.array([-6.0, 26.0])
    lo, hi = np.floor(np.nanmin(days_cw)) - 1, max(np.ceil(np.nanmax(days_cw)) + 1, p.V2 + 2)
    cw = np.linspace(lo, hi, 321)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cw, y=cw, name="CWV = CW", line=dict(color=t.axis, width=1, dash="dot"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=cw, y=demand.transform(cw, published), name="Published (official)",
                             line=dict(color=t.muted, width=2, dash="dash"),
                             hovertemplate="CW %{x:.1f} °C → CWV %{y:.1f} °C<extra>published</extra>"))
    fig.add_trace(go.Scatter(x=cw, y=demand.transform(cw, p), name="Ours (fitted)", line=dict(color=t.series[0], width=2.5),
                             hovertemplate="CW %{x:.1f} °C → CWV %{y:.1f} °C<extra>ours</extra>"))
    for x, label in ((p.V0, "V0: cold upturn below"), (p.V1, "V1: summer transition"), (p.V2, "V2: summer cut-off")):
        fig.add_vline(x=x, line=dict(color=t.series[0], width=1, dash="dot"),
                      annotation=dict(text=label, font=dict(size=10, color=t.ink_2), textangle=-90, yanchor="top"))
    if frame is not None and fit is not None:  # where this LDZ's days fall: a rug along the bottom
        x = days_cw[~np.isnan(days_cw)]
        fig.add_trace(go.Scattergl(x=x, y=np.full(len(x), cw.min()), mode="markers", name="Days (rug)",
                                   marker=dict(symbol="line-ns", size=10, line=dict(width=1, color=_alpha(t.series[0], 0.25))),
                                   hoverinfo="skip"))
    fig.update_layout(title="From CW to CWV: the summer cut-off and the cold-weather upturn",
                      xaxis_title="CW (°C)", yaxis_title="CWV (°C)", height=420)
    return fig


def cw_series(fit: demand.Fit, frame: pd.DataFrame) -> np.ndarray:
    """The fitted CW (before the transform) for each day."""
    return demand._cw(fit, frame)


def demand_line(fit: demand.Fit, frame: pd.DataFrame) -> go.Figure:
    """Demand against the fitted CWV, with the model's line for an ordinary weekday (Monday, no holiday)."""
    t = active()
    x = demand.cwv_series(fit, frame)
    y = frame["target"].to_numpy()
    ok = ~np.isnan(x) & ~np.isnan(y)
    coef = dict(zip(fit.columns, fit.coef))
    years = pd.DatetimeIndex(frame.index).year.to_numpy() + (pd.DatetimeIndex(frame.index).month.to_numpy() >= 10)
    counts = pd.Series(years[ok]).value_counts()
    latest = counts[counts >= 300].index.max()  # the latest gas year with most of its days
    fig = go.Figure()
    for sel, name, colour, size in ((years != latest, "Earlier gas years", _alpha(t.muted, 0.4), 5),
                                    (years == latest, f"Gas year {latest - 1}/{str(latest)[2:]}", t.series[0], 6)):
        m = ok & sel
        fig.add_trace(go.Scattergl(x=x[m], y=y[m], mode="markers", name=name,
                                   marker=dict(size=size, color=colour, line=dict(width=0)),
                                   customdata=frame.index[m].strftime("%d %b %Y"),
                                   hovertemplate="%{customdata}<br>CWV %{x:.1f} → %{y:,.1f} GWh<extra></extra>"))
    line_x = np.linspace(np.nanmin(x[ok]), np.nanmax(x[ok]), 50)
    fig.add_trace(go.Scatter(x=line_x, y=coef["intercept"] + coef["cwv"] * line_x, name="Model, ordinary weekday",
                             line=dict(color=t.ink, width=2), hovertemplate="CWV %{x:.1f} → %{y:,.1f} GWh<extra></extra>"))
    fig.update_layout(title="Demand from the CWV", xaxis_title="Our CWV (°C)", yaxis_title="Total − DM (GWh / day)",
                      height=440, hovermode="closest")
    return fig


def calendar_effects(fit: demand.Fit) -> go.Figure:
    """The calendar terms: GWh/day against an ordinary Monday."""
    t = active()
    coef = dict(zip(fit.columns, fit.coef))
    names = {"tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday", "sat": "Saturday",
             "sun": "Sunday", "bank_holiday": "Bank holiday", "christmas": "Christmas period"}
    keys = [k for k in names if k in coef]
    fig = go.Figure(go.Bar(y=[names[k] for k in keys], x=[coef[k] for k in keys], orientation="h",
                           marker=dict(color=[t.series[1] if coef[k] < 0 else t.series[0] for k in keys]),
                           hovertemplate="%{y}: %{x:.1f} GWh/day<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=t.axis, width=1))
    fig.update_layout(title="Calendar effects (vs an ordinary Monday)", xaxis_title="GWh / day", height=320,
                      yaxis=dict(autorange="reversed"), showlegend=False)
    return fig


def recency(fit: demand.Fit, frame: pd.DataFrame, half_life: float) -> go.Figure:
    """How much each past day counts in the fit."""
    t = active()
    days = frame.index[frame["target"].notna()]
    w = demand.recency_weights(days, np.ones(len(days), bool), half_life)
    fig = go.Figure(go.Scatter(x=days, y=w, fill="tozeroy", line=dict(color=t.series[0], width=1.5),
                               fillcolor=_alpha(t.series[0], 0.2), hovertemplate="%{x|%d %b %Y}: weight %{y:.2f}<extra></extra>"))
    fig.update_layout(title=f"Recency weighting: each day's weight in the fit (half-life {half_life:g} year)",
                      yaxis_title="Weight", yaxis_range=[0, 1.05], height=300, showlegend=False)
    return fig


def drift(fit: demand.Fit, frame: pd.DataFrame) -> go.Figure:
    """Monthly mean of (actual − model with today's coefficients): how demand moved relative to now."""
    t = active()
    resid = (frame["target"] - demand.predict(fit, frame)).groupby(pd.Grouper(freq="MS")).mean().dropna()
    fig = go.Figure(go.Bar(x=resid.index, y=resid, marker=dict(color=[t.series[0] if v >= 0 else t.series[1] for v in resid]),
                           hovertemplate="%{x|%b %Y}: %{y:.1f} GWh/day<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=t.axis, width=1))
    fig.update_layout(title="Actual minus today's model, monthly mean", yaxis_title="GWh / day", height=320,
                      showlegend=False)
    return fig


PARAMETERS = [  # name, meaning, unit, published key (None: not comparable)
    ("y", "Effective-temperature memory (share of yesterday's E)", "", "y"),
    ("I2", "Wind-chill strength", "per (m/s · °C)", "I2"),
    ("W0", "Wind speed above which wind chill applies", "m/s", "W0"),
    ("T0", "Temperature below which wind chill applies", "°C", "T0"),
    ("S0", "Solar strength", "per W m⁻²", None),
    ("Sc", "Size of the seasonal shape", "°C", None),
    ("V0", "Cold-weather upturn starts below", "°C", "V0"),
    ("I3", "Cold-weather upturn strength", "", "I3"),
    ("V1", "Summer transition starts at", "°C", "V1"),
    ("V2", "Summer cut-off at", "°C", "V2"),
    ("q", "Slope in the summer transition", "", "q"),
]


def parameter_table(fit: demand.Fit, ldz: str) -> pd.DataFrame:
    """Our fitted CWV parameters against the published ones, in our units (wind in m/s)."""
    pub = cwv.PUBLISHED[ldz]
    rows = []
    for name, meaning, unit, key in PARAMETERS:
        ours = fit.params.V2 if name == "V2" else getattr(fit.params, name)
        if key is None:
            published = "—"
        else:
            v = pub[key] / KNOT if key == "I2" else pub[key] * KNOT if key == "W0" else pub[key]
            published = f"{v:.3g}"
        rows.append({"Parameter": name, "What it is": meaning, "Ours": f"{ours:.3g}", "Published": published,
                     "Unit": unit})
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame) -> str:
    """A small frame as a Markdown table (reads better than an interactive table for a dozen rows)."""
    rows = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    rows += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(rows)


def linear_table(fit: demand.Fit) -> pd.DataFrame:
    coef = dict(zip(fit.columns, fit.coef))
    return pd.DataFrame([{"Term": "Intercept (a)", "Value": f"{coef['intercept']:.1f}", "Unit": "GWh/day"},
                         {"Term": "Slope on CWV (b)", "Value": f"{coef['cwv']:.2f}", "Unit": "GWh/day per °C"}])


__all__ = ["heating_profile", "gas_day_temperature", "effective_temperature", "wind_chill", "solar", "seasonal_shape",
           "transform", "demand_line", "calendar_effects", "recency", "drift", "parameter_table", "linear_table",
           "markdown_table"]
