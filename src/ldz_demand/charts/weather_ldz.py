"""
Charts for LDZ weather: how much the LDZ temperature (or wind) depends on the map method and weighting.

Every variant is compared with a reference variant, day by day. What matters for the demand model is
the day-to-day part of the difference: a constant offset is absorbed when the model is fitted, so the
headline measure is the standard deviation of the daily difference, not the mean.

Colour follows the membership (the same slots as the LDZ geography page, station last); the marker
follows the weighting (filled: gas, open: area).
"""

import pandas as pd
import plotly.graph_objects as go

from ldz_demand.charts import coastline
from ldz_demand.charts.era5 import _mercator_mid
from ldz_demand.charts.geography import METHODS
from ldz_demand.charts.style import active

MEMBERSHIP_LABELS = {"authority": "Local authority", "voronoi": "Voronoi", "hybrid": "Hybrid", "sampled": "Sampled",
                     "station": "Station (official CWV)"}
WEIGHTING_LABELS = {"area": "area", "gas": "gas use", "point": "one station"}
UNITS = {"t2m": "°C", "ws10": "m/s"}
REFERENCE = ("sampled", "gas")


def label(variant: tuple[str, str]) -> str:
    membership, weighting = variant
    if membership == "station":
        return MEMBERSHIP_LABELS["station"]
    return f"{MEMBERSHIP_LABELS[membership]} · {WEIGHTING_LABELS[weighting]}"


def _colour(membership: str) -> str:
    t = active()
    slot = list(METHODS).index(membership) if membership in METHODS else len(METHODS)
    return t.series[slot]


def _marker(variant: tuple[str, str], size: int = 10) -> dict:
    t = active()
    colour = _colour(variant[0])
    if variant[1] == "area":
        return dict(size=size, symbol="circle-open", color=colour, line=dict(width=2, color=colour))
    return dict(size=size, symbol="circle", color=colour, line=dict(width=2, color=t.surface))


def wide(weather: pd.DataFrame, variable: str = "t2m") -> pd.DataFrame:
    """Daily values, index gas_day, columns (ldz, membership, weighting)."""
    w = weather[weather["variable"] == variable]
    return w.pivot_table(index="gas_day", columns=["ldz", "membership", "weighting"], values="value").sort_index()


def comparison(weather: pd.DataFrame, variable: str = "t2m", reference: tuple[str, str] = REFERENCE) -> pd.DataFrame:
    """Per LDZ and variant, vs the reference: mean offset, SD of the daily difference, largest gap, correlation."""
    data = wide(weather, variable)
    rows = []
    for ldz in sorted(data.columns.get_level_values("ldz").unique()):
        block = data[ldz]
        if reference not in block:
            continue
        ref = block[reference]
        for variant in block.columns:
            if variant == reference:
                continue
            diff = (block[variant] - ref).dropna()
            rows.append({"ldz": ldz, "membership": variant[0], "weighting": variant[1], "variant": label(variant),
                         "mean_diff": diff.mean(), "sd_diff": diff.std(), "max_abs_diff": diff.abs().max(),
                         "corr": block[variant].corr(ref), "days": len(diff)})
    return pd.DataFrame(rows)


def spread_chart(stats: pd.DataFrame, variable: str = "t2m", metric: str = "sd_diff",
                 reference: tuple[str, str] = REFERENCE) -> go.Figure:
    """Dot chart: one row per LDZ, one dot per variant, x = the chosen difference measure vs the reference."""
    t = active()
    titles = {"sd_diff": "Day-to-day difference (SD)", "mean_diff": "Mean offset", "max_abs_diff": "Largest daily difference"}
    order = stats.groupby("ldz")[metric].max().sort_values().index.tolist()  # biggest differences at the top
    fig = go.Figure()
    for ldz in order:
        xs = stats.loc[stats["ldz"] == ldz, metric]
        fig.add_trace(go.Scatter(x=[xs.min(), xs.max()], y=[ldz, ldz], mode="lines", line=dict(color=t.axis, width=2),
                                 hoverinfo="skip", showlegend=False))
    variants = stats[["membership", "weighting"]].drop_duplicates()
    for v in sorted(map(tuple, variants.to_numpy()), key=lambda mw: (mw[0] == "station",) + mw):
        s = stats[(stats["membership"] == v[0]) & (stats["weighting"] == v[1])].set_index("ldz").reindex(order)
        fig.add_trace(go.Scatter(
            x=s[metric], y=order, mode="markers", name=label(v), marker=_marker(v),
            customdata=s[["mean_diff", "sd_diff", "max_abs_diff", "corr"]].to_numpy(),
            hovertemplate=(f"%{{y}} · {label(v)}<br>mean offset %{{customdata[0]:+.2f}} {UNITS[variable]}"
                           f"<br>SD of daily difference %{{customdata[1]:.2f}}<br>largest %{{customdata[2]:.2f}}"
                           "<br>correlation %{customdata[3]:.4f}<extra></extra>")))
    unit = UNITS[variable]
    fig.update_layout(
        title=f"{titles[metric]} from {label(reference)}, by LDZ ({unit})", xaxis_title=f"{unit}",
        height=560, hovermode="closest", yaxis=dict(showgrid=False), margin=dict(t=72, b=130),
        legend=dict(orientation="h", x=0, xanchor="left", y=-0.14, yanchor="top"))
    if metric == "mean_diff":
        fig.add_vline(x=0, line=dict(color=t.axis, width=1))
    return fig


def difference_chart(weather: pd.DataFrame, ldz: str, variants: list[tuple[str, str]], variable: str = "t2m",
                     reference: tuple[str, str] = REFERENCE) -> go.Figure:
    """Daily difference from the reference for one LDZ, one line per variant."""
    t = active()
    block = wide(weather, variable)[ldz]
    fig = go.Figure()
    fig.add_hline(y=0, line=dict(color=t.axis, width=1))
    for v in variants:
        if v == reference or v not in block:
            continue
        diff = block[v] - block[reference]
        fig.add_trace(go.Scatter(x=diff.index, y=diff, mode="lines", name=label(v),
                                 line=dict(color=_colour(v[0]), width=2 if v[1] == "gas" else 1.5,
                                           dash="solid" if v[1] != "area" else "dot"),
                                 hovertemplate=f"%{{x|%d %b %Y}}: %{{y:+.2f}} {UNITS[variable]}<extra>{label(v)}</extra>"))
    fig.update_layout(title=f"{ldz}: daily difference from {label(reference)} ({UNITS[variable]})",
                      yaxis_title=UNITS[variable], height=420, hovermode="x unified", margin=dict(t=64, b=40),
                      xaxis=dict(rangeslider=dict(visible=True, thickness=0.06)))
    return fig


def series_chart(weather: pd.DataFrame, ldz: str, variants: list[tuple[str, str]], variable: str = "t2m") -> go.Figure:
    """The daily values themselves for one LDZ (they mostly overlap — the difference chart is easier to read)."""
    block = wide(weather, variable)[ldz]
    fig = go.Figure()
    for v in variants:
        if v in block:
            fig.add_trace(go.Scatter(x=block.index, y=block[v], mode="lines", name=label(v),
                                     line=dict(color=_colour(v[0]), width=1.5, dash="solid" if v[1] != "area" else "dot"),
                                     hovertemplate=f"%{{x|%d %b %Y}}: %{{y:.1f}} {UNITS[variable]}<extra>{label(v)}</extra>"))
    fig.update_layout(title=f"{ldz}: daily gas-day mean ({UNITS[variable]})", yaxis_title=UNITS[variable], height=380,
                      hovermode="x unified", margin=dict(t=64, b=40))
    return fig


def weights_map(weights: pd.DataFrame, ldz: str, variant: tuple[str, str], variable: str = "t2m") -> go.Figure:
    """Where one LDZ's weather comes from: ERA5 cells sized and shaded by their weight."""
    t = active()
    w = weights[(weights["ldz"] == ldz) & (weights["membership"] == variant[0]) & (weights["weighting"] == variant[1])
                & (weights["variable"] == variable)]
    fig = go.Figure()
    coast_lon, coast_lat = coastline.load()
    fig.add_trace(go.Scattergeo(lon=coast_lon, lat=coast_lat, mode="lines", line=dict(color=t.ink_2, width=1),
                                hoverinfo="skip", showlegend=False))
    top = w["weight"].max() if len(w) else 1.0
    fig.add_trace(go.Scattergeo(
        lon=w["lon"], lat=w["lat"], mode="markers", showlegend=False,
        marker=dict(symbol="square", size=(4 + 16 * (w["weight"] / top) ** 0.5), color=w["weight"],
                    colorscale=[[i / (len(t.sequential) - 1), c] for i, c in enumerate(t.sequential)], cmin=0, cmax=top,
                    line=dict(width=0), colorbar=dict(title=dict(text="weight"), outlinewidth=0, thickness=10, len=0.6)),
        text=[f"{la:.2f}°N {lo:.2f}°E: {x:.1%}" for la, lo, x in zip(w["lat"], w["lon"], w["weight"])],
        hovertemplate="%{text}<extra></extra>"))
    south, north, west, east = 49.85, 59.0, -8.2, 1.9
    fig.update_geos(projection_type="mercator", resolution=50, lataxis_range=[south, north], lonaxis_range=[west, east],
                    center=dict(lat=_mercator_mid(south, north), lon=(west + east) / 2), showland=True,
                    landcolor=t.surface, showocean=True, oceancolor=t.page, showcoastlines=False, showcountries=False,
                    showlakes=False, bgcolor=t.surface, showframe=False)
    fig.update_layout(title=f"{ldz}: where its {'temperature' if variable == 't2m' else 'wind'} comes from — {label(variant)}"
                            f" ({len(w)} cells)", height=640, margin=dict(l=8, r=8, t=64, b=8))
    return fig
