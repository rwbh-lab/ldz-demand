"""
The history of the forecast runs with their ranges, not just their medians: four ways to look at it, side
by side on the Live forecasts page while we choose between them.

Each run stores seven percentiles per LDZ and gas day (P05 ... P95). Where a chart needs a whole
distribution (densities, probabilities, a blend of runs), it is rebuilt from those seven points: the
percentiles are joined smoothly in normal-score space (z = Φ⁻¹(q)), and the line through the outer
two is carried on beyond them. That is exact for a normal distribution and follows any skew between the
stored points; the far tails (beyond P05 and P95) are an extrapolation.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.special import ndtr, ndtri

from ldz_demand.charts.forecasts import _alpha, add_actuals, closed_out, run_age_legend
from ldz_demand.charts.style import active

LEVELS = np.array([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
COLS = ["p05", "p10", "p25", "p50", "p75", "p90", "p95"]
Z = ndtri(LEVELS)
YAXIS = "Total − DM (GWh / day)"


# --- distributions from seven percentiles -------------------------------------------------------------

def _z_of(x: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Normal score of each value in `x` (any shape) for one forecast's percentiles `q`: a smooth monotone
    curve (PCHIP) through the stored points, so the density has no kinks, carried on as a straight line
    beyond P05 and P95."""
    from scipy.interpolate import PchipInterpolator

    q = np.asarray(q, float) + np.arange(len(q)) * 1e-6  # strictly increasing, even with rounding ties
    f = PchipInterpolator(q, Z, extrapolate=False)
    lo_slope, hi_slope = f.derivative()([q[0], q[-1]])
    z = f(np.clip(x, q[0], q[-1]))
    z = np.where(x < q[0], Z[0] + (x - q[0]) * lo_slope, z)
    return np.where(x > q[-1], Z[-1] + (x - q[-1]) * hi_slope, z)


def cdf(x: np.ndarray, q: np.ndarray) -> np.ndarray:
    """P(demand <= x) for one forecast's percentiles."""
    return ndtr(_z_of(np.asarray(x, float), np.asarray(q, float)))


def density(x: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Approximate probability density (per GWh) from the percentiles, by differencing the CDF."""
    x = np.asarray(x, float)
    return np.gradient(cdf(x, q), x)


def _quantiles_of_mixture(qs: np.ndarray, weights: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """Percentiles of a weighted mixture of forecasts (rows of `qs`), found on a fine grid."""
    lo, hi = qs[:, 0].min(), qs[:, -1].max()
    pad = (hi - lo) * 0.5 + 1.0
    grid = np.linspace(lo - pad, hi + pad, 2001)
    mix = sum(w * cdf(grid, q) for w, q in zip(weights, qs)) / weights.sum()
    return np.interp(levels, mix, grid)


def _rgba(colour: str, alpha: float) -> str:
    """A colour from the theme ("#rrggbb") or from plotly's scales ("rgb(r, g, b)") with transparency."""
    if colour.startswith("#"):
        return _alpha(colour, alpha)
    return colour.replace("rgb(", "rgba(").replace(")", f", {alpha})")


# --- choosing a gas day ----------------------------------------------------------------------------

def default_target_day(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str) -> pd.Timestamp:
    """The latest gas day with an actual among those forecast by the most runs (else the most covered day)."""
    w = runs[runs["ldz"] == ldz]
    count = w.groupby("gas_day")["run_date"].nunique()
    best = count[count == count.max()].index
    known = set(actual.loc[actual["ldz"] == ldz, "gas_day"])
    with_actual = [d for d in best if d in known]
    return max(with_actual) if with_actual else max(best)


def target_days(runs: pd.DataFrame, ldz: str, min_runs: int = 2) -> list[pd.Timestamp]:
    count = runs[runs["ldz"] == ldz].groupby("gas_day")["run_date"].nunique()
    return sorted(count[count >= min_runs].index, reverse=True)


def _actual_for(actual: pd.DataFrame, ldz: str, gas_day) -> pd.Series | None:
    a = actual[(actual["ldz"] == ldz) & (actual["gas_day"] == gas_day)]
    return None if a.empty else a.iloc[0]


# --- B · ridgeline of densities -----------------------------------------------------------------------

def ridgeline(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str, gas_day) -> go.Figure:
    """The same gas day, each run's forecast as a density curve, stacked by lead: shape as well as width."""
    from plotly.colors import sample_colorscale

    t = active()
    f = runs[(runs["ldz"] == ldz) & (runs["gas_day"] == gas_day)].sort_values("lead_days", ascending=False)
    qs = f[COLS].to_numpy(float)
    lo, hi = qs[:, 0].min(), qs[:, -1].max()
    pad = (hi - lo) * 0.25
    grid = np.linspace(lo - pad, hi + pad, 400)
    dens = np.array([density(grid, q) for q in qs])
    scale = 1.6 / dens.max()                      # the tallest curve rises 1.6 rows
    ramp = [[i / (len(t.sequential) - 1), c] for i, c in enumerate(t.sequential)]
    n = len(f)
    fig = go.Figure()
    for i, (row, d) in enumerate(zip(f.itertuples(), dens)):
        base = n - 1 - i                          # longest lead at the top, D−0 at the bottom
        colour = sample_colorscale(ramp, [0.25 + 0.75 * i / max(n - 1, 1)])[0]
        label = f"D−{int(row.lead_days)} · {pd.Timestamp(row.run_date):%d %b}"
        fig.add_trace(go.Scatter(x=grid, y=np.full_like(grid, base), mode="lines", line=dict(width=0),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=grid, y=base + d * scale, mode="lines", fill="tonexty", name=label,
                                 line=dict(color=colour, width=1.5), fillcolor=_rgba(colour, 0.35), showlegend=False,
                                 hovertemplate=f"{label}: median {row.p50:,.0f}, 10–90% {row.p10:,.0f}–{row.p90:,.0f}<extra></extra>"))
    a = _actual_for(actual, ldz, gas_day)
    if a is not None:
        if "lo" in a and pd.notna(a["lo"]):  # the actual's own 10–90% range
            fig.add_vrect(x0=a["lo"], x1=a["hi"], fillcolor=_alpha(t.serious, 0.15), line_width=0, layer="below")
        kind = "provisional" if a["provisional"] else "closed out"
        fig.add_vline(x=a["actual"], line=dict(color=t.serious, width=2, dash="dash"),
                      annotation_text=f"actual {a['actual']:,.0f} ({kind})", annotation_position="top")
    fig.update_layout(title=f"How the forecast of {pd.Timestamp(gas_day):%a %d %b %Y} took shape, {ldz}",
                      xaxis_title=YAXIS, height=max(420, 34 * n + 140), hovermode="closest",
                      yaxis=dict(tickvals=list(range(n)), showgrid=False, zeroline=False,
                                 ticktext=[f"D−{int(d)} · {pd.Timestamp(r):%d %b}"
                                           for d, r in zip(f["lead_days"][::-1], f["run_date"][::-1])]))
    return fig


# --- C · lagged-ensemble blend ------------------------------------------------------------------------

WEIGHTINGS = {
    "Newer runs count more (half-life 2 days)": "decay",
    "By each run's own spread (inverse variance)": "spread",
    "Equal": "equal",
}
HALF_LIFE_DAYS = 2.0


def _weights(block: pd.DataFrame, as_of: pd.Timestamp, how: str) -> np.ndarray:
    if how == "equal":
        return np.ones(len(block))
    if how == "spread":  # σ from the 10–90% width (2 × 1.2816 σ for a normal)
        sigma = (block["p90"] - block["p10"]).to_numpy(float) / 2.563
        return 1.0 / np.maximum(sigma, 1e-6) ** 2
    age = (as_of - block["run_date"]).dt.days.to_numpy(float)
    return 0.5 ** (age / HALF_LIFE_DAYS)


def blend(runs: pd.DataFrame, ldz: str, as_of, how: str = "decay") -> pd.DataFrame:
    """For each gas day of the `as_of` run: a weighted mixture of every run up to `as_of` that covered the
    day. Weights are renormalised over the runs that exist, so the far days (one or two runs) fall back to
    the newest run alone."""
    as_of = pd.Timestamp(as_of)
    w = runs[(runs["ldz"] == ldz) & (runs["run_date"] <= as_of)]
    days = sorted(w.loc[w["run_date"] == as_of, "gas_day"])
    rows = []
    levels = np.array([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
    for d in days:
        block = w[w["gas_day"] == d]
        wt = _weights(block, as_of, how)
        q = _quantiles_of_mixture(block[COLS].to_numpy(float), wt, levels)
        newest = block[block["run_date"] == as_of].iloc[0]
        rows.append({"gas_day": d, "lead_days": int(newest["lead_days"]), "runs": len(block),
                     "newest_share": float(wt[block["run_date"].to_numpy() == as_of].sum() / wt.sum()),
                     **dict(zip(COLS, q)), **{f"single_{c}": newest[c] for c in ("p10", "p50", "p90")}})
    return pd.DataFrame(rows)


def blend_score(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str, how: str) -> dict | None:
    """Every run with closed-out (D+6) demand, blended as of that run, against the run on its own: how often
    the actual fell inside the 10–90% range, the mean absolute error of the median, and the mean width."""
    a = closed_out(actual)
    a = a[a["ldz"] == ldz][["gas_day", "actual"]]
    out = []
    for rd in sorted(runs.loc[runs["ldz"] == ldz, "run_date"].unique()):
        b = blend(runs, ldz, rd, how).merge(a, on="gas_day")
        out.append(b)
    s = pd.concat(out) if out else pd.DataFrame()
    if s.empty:
        return None
    inside = lambda lo, hi: ((s["actual"] >= s[lo]) & (s["actual"] <= s[hi])).mean() * 100  # noqa: E731
    return dict(days=len(s), blend_cover=inside("p10", "p90"), single_cover=inside("single_p10", "single_p90"),
                blend_mae=(s["p50"] - s["actual"]).abs().mean(), single_mae=(s["single_p50"] - s["actual"]).abs().mean(),
                blend_width=(s["p90"] - s["p10"]).mean(), single_width=(s["single_p90"] - s["single_p10"]).mean())


def blend_chart(b: pd.DataFrame, actual: pd.DataFrame, ldz: str, as_of, how_label: str) -> go.Figure:
    t = active()
    x = list(b["gas_day"]) + list(b["gas_day"][::-1])
    fig = go.Figure()
    for lo, hi, alpha, name in (("p05", "p95", 0.12, "Blend 5–95%"), ("p10", "p90", 0.22, "Blend 10–90%"),
                                ("p25", "p75", 0.38, "Blend 25–75%")):
        fig.add_trace(go.Scatter(x=x, y=list(b[hi]) + list(b[lo][::-1]), fill="toself", name=name,
                                 fillcolor=_alpha(t.series[0], alpha), line=dict(width=0), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=b["gas_day"], y=b["p50"], name="Blend median", line=dict(color=t.series[0], width=2.5),
                             customdata=np.stack([b["p10"], b["p90"], b["runs"], b["newest_share"] * 100], axis=1),
                             hovertemplate="%{x|%a %d %b}: %{y:,.0f} (10–90%: %{customdata[0]:,.0f}–%{customdata[1]:,.0f})"
                                           " · %{customdata[2]} runs, newest %{customdata[3]:.0f}% of the weight<extra>blend</extra>"))
    for col, name in (("single_p50", "This run alone, median"), ("single_p10", "This run alone, 10–90%"),
                      ("single_p90", None)):
        fig.add_trace(go.Scatter(x=b["gas_day"], y=b[col], name=name or "", showlegend=name is not None,
                                 legendgroup=col[-3:] if col != "single_p50" else None,
                                 line=dict(color=t.ink_2, width=1.5 if col == "single_p50" else 1,
                                           dash="solid" if col == "single_p50" else "dot"),
                                 hovertemplate="%{x|%a %d %b}: %{y:,.0f}<extra>this run</extra>"))
    add_actuals(fig, actual[(actual["ldz"] == ldz) & actual["gas_day"].isin(b["gas_day"])])
    fig.update_layout(title=f"Blend of every run up to {pd.Timestamp(as_of):%a %d %b}, {ldz} — {how_label.lower()}",
                      yaxis_title=YAXIS, height=520, hovermode="x unified",
                      legend=dict(orientation="h", y=-0.12, yanchor="top", x=0, xanchor="left"))
    return fig


# --- D · run × gas-day heatmap ------------------------------------------------------------------------

HEATMAP_MEASURES = {
    "Error against the actual (%)": "error",
    "Width of the 10–90% range": "width",
    "Median": "p50",
}
HEATMAP_ROWS = {"Run": "run_date", "Days ahead": "lead_days"}


def _with_error(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str) -> pd.DataFrame:
    """One LDZ's forecasts with the median's error against closed-out (D+6) demand, in % (NaN until then)."""
    actual = closed_out(actual)
    w = runs[runs["ldz"] == ldz].merge(actual.loc[actual["ldz"] == ldz, ["gas_day", "actual"]], on="gas_day", how="left")
    w["error"] = (w["p50"] - w["actual"]) / w["actual"] * 100
    return w


def error_by_lead(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str) -> pd.DataFrame:
    """Mean and mean absolute error of the median (%) per lead-day band, over the days published so far."""
    w = _with_error(runs, actual, ldz).dropna(subset=["error"])
    band = pd.cut(w["lead_days"], [-1, 2, 6, 13], labels=["D−0 to D−2", "D−3 to D−6", "D−7 to D−13"])
    return w.groupby(band, observed=True)["error"].agg(mean="mean", mae=lambda e: e.abs().mean(), days="size")


def run_heatmap(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str, measure: str = "error",
                rows: str = "run_date") -> go.Figure:
    """Every forecast at once, coloured by its error against the actual (or its width, or its median).
    Rows are runs (oldest at the top, so reading down a column follows the day's forecasts as it approached)
    or days ahead (D−0 at the top: a band of one colour across a row is a bias at that lead)."""
    t = active()
    w = _with_error(runs, actual, ldz)
    if measure == "error":
        w["value"] = w["error"]
        scale = [[i / (len(t.diverging) - 1), c] for i, c in enumerate(t.diverging)]
        lim = float(np.nanpercentile(np.abs(w["value"]), 98)) if w["value"].notna().any() else 1.0
        z_args = dict(colorscale=scale, zmid=0, zmin=-lim, zmax=lim)
        unit, fmt, title = "% vs actual", "%{z:.1f}%", "Error of each forecast's median against the actual"
    else:
        w["value"] = w["p90"] - w["p10"] if measure == "width" else w["p50"]
        z_args = dict(colorscale=[[i / (len(t.sequential) - 1), c] for i, c in enumerate(t.sequential)])
        unit, fmt = "GWh", "%{z:,.0f} GWh"
        title = "Width of each forecast's 10–90% range" if measure == "width" else "Each forecast's median"
    other = "lead_days" if rows == "run_date" else "run_date"
    grid = w.pivot_table(index=rows, columns="gas_day", values="value", dropna=False)
    grid = grid.dropna(how="all").dropna(axis=1, how="all").sort_index(ascending=False)
    info = w.pivot_table(index=rows, columns="gas_day", values=other, aggfunc="first").reindex_like(grid)
    if rows == "run_date":
        y = [f"{d:%d %b}" for d in grid.index]
        info = info.to_numpy()
        hover = "%{y} run → %{x|%a %d %b} (D−%{customdata:.0f}): " + fmt
        ytitle = "Run (00z)"
    else:
        y = [f"D−{int(d)}" for d in grid.index]
        info = info.apply(lambda c: pd.to_datetime(c).dt.strftime("%d %b")).to_numpy()
        hover = "%{y}, %{customdata} run → %{x|%a %d %b}: " + fmt
        ytitle = "Days ahead"
    fig = go.Figure(go.Heatmap(z=grid.to_numpy(), x=grid.columns, y=y, customdata=info, colorbar=dict(title=unit),
                               hoverongaps=False, hovertemplate=hover + "<extra></extra>", **z_args))
    fig.update_layout(title=f"{title}, {ldz}", xaxis_title="Gas day", yaxis_title=ytitle,
                      height=max(420, 22 * len(grid) + 160))
    return fig


# --- E · probability of exceeding a threshold ---------------------------------------------------------

def default_threshold(runs: pd.DataFrame, ldz: str) -> float:
    """A round level near the top quarter of recent medians: high enough to be a question, low enough to happen."""
    p = runs.loc[runs["ldz"] == ldz, "p50"].quantile(0.75)
    step = 50 if p > 500 else 5
    return float(round(p / step) * step)


def exceedance(runs: pd.DataFrame, actual: pd.DataFrame, ldz: str, threshold: float) -> go.Figure:
    """P(demand > threshold) for each gas day, one line per run (faded with age, as above); the actual
    marked at 100% where it was exceeded and 0% where not."""
    from plotly.colors import sample_colorscale

    t = active()
    w = runs[runs["ldz"] == ldz]
    dates = sorted(w["run_date"].unique())
    n = len(dates)
    ramp = [[i / (len(t.sequential) - 1), c] for i, c in enumerate(t.sequential)]
    fig = go.Figure()
    for i, rd in enumerate(dates):
        f = w[w["run_date"] == rd].sort_values("gas_day")
        p = [100 * (1 - cdf(threshold, q)) for q in f[COLS].to_numpy(float)]
        age = (n - 1 - i) / max(n - 1, 1)
        fig.add_trace(go.Scatter(x=f["gas_day"], y=p, name=f"{pd.Timestamp(rd):%d %b} run", showlegend=False,
                                 line=dict(color=sample_colorscale(ramp, [0.2 + 0.8 * (1 - age)])[0],
                                           width=3 if i == n - 1 else 1.5), opacity=1.0 - 0.6 * age,
                                 hovertemplate="%{x|%d %b}: %{y:.0f}%"))
    run_age_legend(fig, dates, ramp)
    a = actual[(actual["ldz"] == ldz) & (actual["gas_day"] >= w["gas_day"].min())]
    if not a.empty:
        over = a["actual"] > threshold
        fig.add_trace(go.Scatter(x=a["gas_day"], y=np.where(over, 100, 0), mode="markers", name="Actual (over / not)",
                                 marker=dict(size=9, color=np.where(over, t.serious, t.ink)),
                                 customdata=a["actual"], hovertemplate="%{x|%d %b}: actual %{customdata:,.0f} GWh<extra></extra>"))
    fig.update_layout(title=f"Chance of demand above {threshold:,.0f} GWh/day, {ldz}, by run",
                      yaxis=dict(title="Probability (%)", range=[-5, 105]), height=520, hovermode="x unified")
    return fig
