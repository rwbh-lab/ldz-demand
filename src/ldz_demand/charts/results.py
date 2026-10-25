"""
Charts and tables for the Backtesting results page, from the compact results bundle (ldz_demand.models.results).
All GB: the sum of the 13 LDZs, on days every LDZ has.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ldz_demand.charts.style import active

NAMES = {"final": "Our model", "official": "Official CWV", "ng": "National Gas forecast", "ours": "Our model"}
WINTER = (11, 12, 1, 2, 3)


def _pct(err: pd.Series, actual: pd.Series) -> float:
    return float((err.abs() / actual * 100).mean())


def _rmse(err: pd.Series) -> float:
    return float(np.sqrt((err ** 2).mean()))


def headline(daily: pd.DataFrame) -> pd.DataFrame:
    """Per forward gas year and season: RMSE and MAPE, ours and (where it can be scored) the official CWV."""
    rows = []
    d = daily.assign(season=np.where(daily["gas_day"].dt.month.isin(WINTER), "Winter", "Summer"))
    for (year, season), g in pd.concat([d, d.assign(season="All days")]).groupby(["held_out", "season"]):
        row = {"Gas year": year, "Days": season, "n": len(g)}
        for model in ("final", "official"):
            ok = g[model].notna()
            err = g.loc[ok, model] - g.loc[ok, "actual"]
            row[f"{NAMES[model]} RMSE"] = f"{_rmse(err):.1f}" if ok.all() else "—"
            row[f"{NAMES[model]} error"] = f"{_pct(err, g.loc[ok, 'actual']):.1f}%" if ok.all() else "—"
        rows.append(row)
    out = pd.DataFrame(rows)
    order = {"All days": 0, "Winter": 1, "Summer": 2}
    return out.sort_values(["Gas year", "Days"], key=lambda c: c.map(order) if c.name == "Days" else c).reset_index(drop=True)


def benchmark_table(bench: pd.DataFrame) -> pd.DataFrame:
    rows = []
    b = bench.assign(season=np.where(bench["gas_day"].dt.month.isin(WINTER), "Winter", "Summer"))
    for (year, season), g in pd.concat([b, b.assign(season="All days")]).groupby(["held_out", "season"]):
        row = {"Gas year": year, "Days": season, "n": len(g)}
        for k in ("ng", "ours"):
            err = g[k] - g["total"]
            row[f"{NAMES[k]} error"] = f"{_pct(err, g['total']):.1f}%"
            row[f"{NAMES[k]} RMSE"] = f"{_rmse(err):.1f}"
        rows.append(row)
    order = {"All days": 0, "Winter": 1, "Summer": 2}
    out = pd.DataFrame(rows)
    return out.sort_values(["Gas year", "Days"], key=lambda c: c.map(order) if c.name == "Days" else c).reset_index(drop=True)


def actual_vs_predicted(daily: pd.DataFrame) -> go.Figure:
    """Days not scored (e.g. SE's repaired days, until Feb 2024) are left as gaps."""
    t = active()
    daily = daily.set_index("gas_day").reindex(pd.date_range(daily["gas_day"].min(), daily["gas_day"].max()))
    daily = daily.rename_axis("gas_day").reset_index()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily["gas_day"], y=daily["actual"], name="Actual", mode="lines",
                             line=dict(color=t.ink, width=1.5), hovertemplate="%{x|%d %b %Y}: %{y:,.0f} GWh"))
    fig.add_trace(go.Scatter(x=daily["gas_day"], y=daily["final"], name=NAMES["final"], mode="lines",
                             line=dict(color=t.series[0], width=1.5), hovertemplate="%{x|%d %b %Y}: %{y:,.0f} GWh"))
    if daily["official"].notna().any():
        fig.add_trace(go.Scatter(x=daily["gas_day"], y=daily["official"], name=NAMES["official"], mode="lines",
                                 line=dict(color=t.series[1], width=1, dash="dot"), visible="legendonly",
                                 hovertemplate="%{x|%d %b %Y}: %{y:,.0f} GWh"))
    fig.update_layout(title="GB demand (total − DM): actual vs predicted, each year from the years before it",
                      yaxis_title="GWh / day", height=420, hovermode="x unified")
    return fig


def errors_by_month(monthly: pd.DataFrame, measure: str = "mape") -> go.Figure:
    t = active()
    label = {"mape": "Mean error per gas day (%)", "rmse": "RMSE (GWh / day)", "bias": "Mean error (GWh / day)"}[measure]
    fig = go.Figure()
    for i, model in enumerate(("final", "official")):
        m = monthly[monthly["model"] == model]
        fmt = "%{y:.1f}%" if measure == "mape" else "%{y:,.1f} GWh"
        fig.add_trace(go.Bar(x=m["month"], y=m[measure], name=NAMES[model], marker=dict(color=t.series[i]),
                             hovertemplate=f"%{{x|%b %Y}}: {fmt}<extra>{NAMES[model]}</extra>"))
    if measure == "bias":
        fig.add_hline(y=0, line=dict(color=t.axis, width=1))
    fig.update_layout(title="GB errors by month", yaxis_title=label, height=380, barmode="group", bargap=0.25)
    return fig


def benchmark_by_month(bench: pd.DataFrame) -> go.Figure:
    t = active()
    b = bench.assign(month=bench["gas_day"].dt.to_period("M").dt.to_timestamp())
    fig = go.Figure()
    for i, k in enumerate(("ng", "ours")):
        m = b.groupby("month").apply(lambda g, k=k: _pct(g[k] - g["total"], g["total"]), include_groups=False)
        fig.add_trace(go.Bar(x=m.index, y=m.values, name=NAMES[k], marker=dict(color=t.series[2 if k == "ng" else 0]),
                             hovertemplate=f"%{{x|%b %Y}}: %{{y:.1f}}%<extra>{NAMES[k]}</extra>"))
    fig.update_layout(title="GB total demand: mean error per gas day, by month", yaxis_title="%", height=380,
                      barmode="group", bargap=0.25)
    return fig


def _model_label(label: str) -> str:
    out = label
    for a, b in (("sampled_gas", "gas-weighted"), ("sampled_area", "area-weighted"), ("cwv_inputs", ""),
                 ("/A", " · target A"), ("/B", " · target B"), ("_", " "), ("/", " · ")):
        out = out.replace(a, b)
    return out.strip()


def experiments_markdown(experiments: pd.DataFrame) -> str:
    """Every experiment's GB scores; the best RMSE in each experiment in bold."""
    gb = experiments[experiments["ldz"] == "GB"]
    lines = ["| Experiment | Model | Days | RMSE | Winter | Coldest | Error |", "|---|---|---|---|---|---|---|"]
    for name, g in gb.groupby("experiment", sort=False):
        g = g.sort_values("rmse_all")
        best = g["rmse_all"].min()
        for i, r in enumerate(g.itertuples()):
            exp = f"{r.number} · {r.title} ({r.scheme})" if i == 0 else ""
            b = "**" if r.rmse_all == best else ""
            lines.append(f"| {exp} | {b}{_model_label(r.input)}{b} | {r.days:,} | {b}{r.rmse_all:.1f}{b} | "
                         f"{r.rmse_winter:.1f} | {r.rmse_cold:.1f} | {r.mape_all:.2f}% |")
    return "\n".join(lines)


def markdown_table(df: pd.DataFrame) -> str:
    rows = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    rows += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(rows)
