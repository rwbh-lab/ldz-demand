"""
Charts for LDZ geography: the local-authority LDZ map and the membership check.

13 LDZs is more than the 8 safe categorical colours, so LDZs are coloured so that neighbours always
differ (a map colouring from the first slots of the palette) and every LDZ is labelled on the map —
colour separates, the label identifies.
"""

import json
from functools import lru_cache

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ldz_demand.charts import coastline
from ldz_demand.charts.era5 import _mercator_mid
from ldz_demand.charts.style import active
from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.geo import boundaries

MAP_SLOTS = 6  # palette slots used for the map colouring


@lru_cache(maxsize=1)
def _ldz_shapes(las_key: str):
    """LDZ outlines (union of their authorities by main LDZ), adjacency and label points."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    main = dict(json.loads(las_key))
    geoms = {f["id"]: shape(f["geometry"]).buffer(0) for f in boundaries.load()["features"]}
    unions = {ldz: unary_union([g for code, g in geoms.items() if main.get(code) == ldz]) for ldz in LDZS}
    touches = {a: {b for b in LDZS if b != a and unions[a].buffer(0.02).intersects(unions[b])} for a in LDZS}
    labels = {}
    for ldz, u in unions.items():
        biggest = max(getattr(u, "geoms", [u]), key=lambda p: p.area)
        pt = biggest.representative_point()
        labels[ldz] = (pt.y, pt.x)
    return touches, labels


def ldz_colours(las: pd.DataFrame) -> dict[str, str]:
    """Map colouring: greedy, in LDZ order, so neighbouring LDZs never share a colour."""
    t = active()
    touches, _ = _ldz_shapes(_key(las))
    slot = {}
    for ldz in sorted(LDZS, key=lambda z: -len(touches[z])):
        used = {slot[n] for n in touches[ldz] if n in slot}
        slot[ldz] = next(i for i in range(MAP_SLOTS) if i not in used)
    return {ldz: t.series[i] for ldz, i in slot.items()}


def ldz_map(las: pd.DataFrame, towns: pd.DataFrame | None = None, view: str = "ldz") -> go.Figure:
    """
    Local authorities coloured by LDZ (view="ldz") or by the winning LDZ's vote share ("confidence").
    Split authorities are faded and outlined; fallback ones (no listed town) outlined.
    """
    t = active()
    geo = boundaries.load()
    df = las.copy()
    df["kind"] = np.select([df["method"] == "split", df["method"].str.startswith("nearest_town")], ["split", "fallback"], "single")
    hover = (df["lad23nm"] + "<br>LDZ: " + df["ldz"] + " (main " + df["main_ldz"] + ")<br>" + df["method"]
             + "<br>votes: " + df["votes"].str.replace('"', ""))
    fig = go.Figure()

    if view == "confidence":
        share = df["share"].fillna(0).astype(float)
        fig.add_trace(go.Choropleth(
            geojson=geo, featureidkey="id", locations=df["lad23cd"], z=share, zmin=0.4, zmax=1,
            colorscale=[[0, t.serious], [0.5, t.sequential[1]], [1, t.series[0]]],
            marker=dict(line=dict(width=0.4, color=t.surface)), text=hover, hovertemplate="%{text}<extra></extra>",
            colorbar=dict(title=dict(text="winning<br>share"), outlinewidth=0, thickness=10, len=0.6),
        ))
    else:
        # one trace (the boundaries are embedded once): colour slot as z, per-authority opacity and outline
        colours = ldz_colours(las)
        palette = list(dict.fromkeys(colours.values()))
        slot = df["main_ldz"].map(lambda z: palette.index(colours[z]))
        n = max(len(palette) - 1, 1)
        scale = []
        for i, c in enumerate(palette):
            scale += [[max(0.0, (i - 0.5) / n), c], [min(1.0, (i + 0.5) / n), c]]
        line_colour = np.select([df["kind"] == "split", df["kind"] == "fallback"], [t.serious, t.accent], t.surface)
        line_width = np.where(df["kind"] == "single", 0.4, 1.6)
        fig.add_trace(go.Choropleth(
            geojson=geo, featureidkey="id", locations=df["lad23cd"], z=slot, zmin=0, zmax=n,
            colorscale=scale, showscale=False,
            marker=dict(opacity=np.where(df["kind"] == "split", 0.4, 0.85).tolist(),
                        line=dict(color=line_colour.tolist(), width=line_width.tolist())),
            text=hover, hovertemplate="%{text}<extra></extra>", name="LDZ", showlegend=False,
        ))
        # legend entries for the outline meanings (labels on the map carry LDZ identity)
        for name, colour in (("Split between LDZs (faded)", t.serious), ("No listed town — nearest town's LDZ", t.accent)):
            fig.add_trace(go.Scattergeo(lon=[None], lat=[None], mode="markers", name=name,
                                        marker=dict(symbol="square-open", size=12, color=colour, line=dict(width=2))))

    if towns is not None:
        placed = towns.dropna(subset=["lat"])
        fig.add_trace(go.Scattergeo(
            lon=placed["lon"], lat=placed["lat"], mode="markers", name="Listed towns",
            marker=dict(size=4, color=t.ink, opacity=0.7, line=dict(width=0)),
            text=placed["town"] + " (" + placed["ldz"] + ")<br>" + placed["method"],
            hovertemplate="%{text}<extra></extra>"))

    coast_lon, coast_lat = coastline.load()
    fig.add_trace(go.Scattergeo(lon=coast_lon, lat=coast_lat, mode="lines", line=dict(color=t.ink_2, width=1),
                                hoverinfo="skip", showlegend=False))
    _, labels = _ldz_shapes(_key(las))
    fig.add_trace(go.Scattergeo(
        lon=[labels[z][1] for z in LDZS], lat=[labels[z][0] for z in LDZS], text=list(LDZS), mode="text",
        textfont=dict(color=t.ink, size=15, family=t.font), hoverinfo="skip", showlegend=False))

    south, north, west, east = 49.85, 59.0, -8.2, 1.9
    fig.update_geos(
        projection_type="mercator", resolution=50, lataxis_range=[south, north], lonaxis_range=[west, east],
        center=dict(lat=_mercator_mid(south, north), lon=(west + east) / 2),
        showland=True, landcolor=t.surface, showocean=True, oceancolor=t.page, showcoastlines=False,
        showcountries=False, showlakes=False, bgcolor=t.surface, showframe=False,
    )
    fig.update_layout(title="LDZ membership by local authority" if view == "ldz" else "Confidence: share of town votes for the winning LDZ",
                      height=820, margin=dict(l=8, r=8, t=64, b=8),
                      legend=dict(orientation="h", x=0, xanchor="left", y=1.0, yanchor="bottom"))
    return fig


def membership_check(las: pd.DataFrame, gas_use: pd.DataFrame, energy: pd.DataFrame | None) -> pd.DataFrame:
    """
    Each LDZ's share of DESNZ annual gas use (our membership; split authorities divided by vote share)
    vs its share of measured National Gas demand (mean of the last three complete gas years).
    """
    use = gas_use.set_index("lad24cd")
    rows = []
    for r in las.itertuples():
        if r.lad24cd not in use.index:
            continue
        votes = json.loads(r.votes) if r.ldz == "split" else {r.ldz: 1}
        total = sum(votes.values())
        for ldz, w in votes.items():
            rows.append({"ldz": ldz, "desnz_gwh": use.loc[r.lad24cd, "gwh_all"] * w / total})
    out = pd.DataFrame(rows).groupby("ldz").sum()
    out["desnz_share"] = 100 * out["desnz_gwh"] / out["desnz_gwh"].sum()
    if energy is not None:
        e = energy.reset_index()
        e = e[e["ldz"] != "GB"]
        end = pd.Timestamp(e["gas_day"].max())
        last_year_end = pd.Timestamp(year=end.year if end.month >= 10 else end.year - 1, month=10, day=1)
        e = e[(e["gas_day"] >= last_year_end - pd.DateOffset(years=3)) & (e["gas_day"] < last_year_end)]
        ng = e.groupby("ldz")["total_repaired"].sum() / 3
        out["ng_share"] = 100 * ng / ng.sum()
        out["difference_pp"] = out["desnz_share"] - out["ng_share"]
    return out.reset_index().sort_values("ng_share" if energy is not None else "desnz_share")


def membership_check_chart(check: pd.DataFrame) -> go.Figure:
    """Dumbbell: DESNZ share vs National Gas share per LDZ."""
    t = active()
    fig = go.Figure()
    for r in check.itertuples():
        fig.add_trace(go.Scatter(x=[r.desnz_share, r.ng_share], y=[r.ldz, r.ldz], mode="lines",
                                 line=dict(color=t.axis, width=2), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=check["ng_share"], y=check["ldz"], mode="markers", name="National Gas demand (measured)",
                             marker=dict(size=10, color=t.series[0], line=dict(width=2, color=t.surface)),
                             hovertemplate="%{y}: %{x:.2f}% of demand<extra></extra>"))
    fig.add_trace(go.Scatter(x=check["desnz_share"], y=check["ldz"], mode="markers", name="DESNZ gas use (our map)",
                             marker=dict(size=10, color=t.series[1], line=dict(width=2, color=t.surface)),
                             customdata=check["difference_pp"],
                             hovertemplate="%{y}: %{x:.2f}% of gas use (%{customdata:+.2f} pp)<extra></extra>"))
    fig.update_layout(title="Each LDZ's share of GB gas: our map vs measured demand", xaxis_title="% of GB",
                      height=480, hovermode="closest", yaxis=dict(showgrid=False))
    return fig


def _key(las: pd.DataFrame) -> str:
    return json.dumps(sorted(zip(las["lad23cd"], las["main_ldz"])))
