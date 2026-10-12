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


METHODS = {"authority": "Local authority (town votes)", "voronoi": "Voronoi (original method)"}
GAP_RANGE = 3.0  # percentage points either side of zero on the gap view


def allocation(las: pd.DataFrame, method: str = "authority") -> pd.DataFrame:
    """Share of each local authority (rows: lad24cd) allocated to each LDZ (columns), per method."""
    if method == "voronoi":
        from ldz_demand.geo import voronoi

        shares = voronoi.authority_shares()
        return shares.rename(index=dict(zip(las["lad23cd"], las["lad24cd"])))
    rows = {}
    for r in las.itertuples():
        votes = json.loads(r.votes) if r.ldz == "split" else {r.ldz: 1.0}
        total = sum(votes.values())
        rows[r.lad24cd] = {ldz: w / total for ldz, w in votes.items()}
    return pd.DataFrame.from_dict(rows, orient="index").reindex(columns=list(LDZS)).fillna(0.0)


def ldz_map(las: pd.DataFrame, towns: pd.DataFrame | None = None, view: str = "ldz", method: str = "authority",
            check: pd.DataFrame | None = None) -> go.Figure:
    """
    LDZ map by method ("authority": local authorities by town vote; "voronoi": the original town
    Voronoi map). view: "ldz" (colour by LDZ), "confidence" (authority method: winning vote share),
    "gap" (each LDZ's percentage-point gap to measured demand; needs `check` from membership_check).
    """
    t = active()
    colours = ldz_colours(las)
    fig = go.Figure()
    gap = None
    if view == "gap" and check is not None:
        col = f"gap_{method}"
        gap = check.set_index("ldz")[col] if col in check else check.set_index("ldz")["difference_pp"]

    if method == "voronoi":
        _voronoi_layer(fig, las, view, colours, gap)
    else:
        _authority_layer(fig, las, view, colours, gap)

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
    text = [f"{z} {gap[z]:+.1f}" if gap is not None and z in gap else z for z in LDZS]
    fig.add_trace(go.Scattergeo(
        lon=[labels[z][1] for z in LDZS], lat=[labels[z][0] for z in LDZS], text=text, mode="text",
        textfont=dict(color=t.ink, size=15, family=t.font), hoverinfo="skip", showlegend=False))

    south, north, west, east = 49.85, 59.0, -8.2, 1.9
    fig.update_geos(
        projection_type="mercator", resolution=50, lataxis_range=[south, north], lonaxis_range=[west, east],
        center=dict(lat=_mercator_mid(south, north), lon=(west + east) / 2),
        showland=True, landcolor=t.surface, showocean=True, oceancolor=t.page, showcoastlines=False,
        showcountries=False, showlakes=False, bgcolor=t.surface, showframe=False,
    )
    titles = {"ldz": "LDZ membership", "confidence": "Confidence: share of town votes for the winning LDZ",
              "gap": "Gap to measured demand: LDZ share of gas use minus share of National Gas demand (pp)"}
    fig.update_layout(title=f"{titles.get(view, '')} — {METHODS[method]}", height=820, margin=dict(l=8, r=8, t=64, b=8),
                      legend=dict(orientation="h", x=0, xanchor="left", y=1.0, yanchor="bottom"))
    return fig


def _gap_colourscale(t):
    stops = t.diverging
    return [[i / (len(stops) - 1), c] for i, c in enumerate(stops)]


def _authority_layer(fig, las, view, colours, gap) -> None:
    t = active()
    geo = boundaries.load()
    df = las.copy()
    df["kind"] = np.select([df["method"] == "split", df["method"].str.startswith("nearest_town")], ["split", "fallback"], "single")
    hover = (df["lad23nm"] + "<br>LDZ: " + df["ldz"] + " (main " + df["main_ldz"] + ")<br>" + df["method"]
             + "<br>votes: " + df["votes"].str.replace('"', ""))
    line_colour = np.select([df["kind"] == "split", df["kind"] == "fallback"], [t.serious, t.accent], t.surface)
    line_width = np.where(df["kind"] == "single", 0.4, 1.6)
    common = dict(geojson=geo, featureidkey="id", locations=df["lad23cd"], hovertemplate="%{text}<extra></extra>")

    if view == "confidence":
        fig.add_trace(go.Choropleth(
            **common, z=df["share"].fillna(0).astype(float), zmin=0.4, zmax=1, text=hover,
            colorscale=[[0, t.serious], [0.5, t.sequential[1]], [1, t.series[0]]],
            marker=dict(line=dict(width=0.4, color=t.surface)),
            colorbar=dict(title=dict(text="winning<br>share"), outlinewidth=0, thickness=10, len=0.6)))
        return
    if view == "gap" and gap is not None:
        z = df["main_ldz"].map(gap).astype(float)
        fig.add_trace(go.Choropleth(
            **common, z=z, zmin=-GAP_RANGE, zmax=GAP_RANGE, colorscale=_gap_colourscale(t),
            text=hover + "<br>LDZ gap: " + z.map(lambda v: f"{v:+.2f} pp"),
            marker=dict(line=dict(width=0.4, color=t.surface)),
            colorbar=dict(title=dict(text="pp"), outlinewidth=0, thickness=10, len=0.6)))
        return
    # one trace (the boundaries are embedded once): colour slot as z, per-authority opacity and outline
    z, scale, n = _slots(df["main_ldz"], colours)
    fig.add_trace(go.Choropleth(
        **common, z=z, zmin=0, zmax=n, colorscale=scale, showscale=False, text=hover,
        marker=dict(opacity=np.where(df["kind"] == "split", 0.4, 0.85).tolist(),
                    line=dict(color=line_colour.tolist(), width=line_width.tolist())),
        name="LDZ", showlegend=False))
    # legend entries for the outline meanings (labels on the map carry LDZ identity)
    for name, colour in (("Split between LDZs (faded)", t.serious), ("No listed town — nearest town's LDZ", t.accent)):
        fig.add_trace(go.Scattergeo(lon=[None], lat=[None], mode="markers", name=name,
                                    marker=dict(symbol="square-open", size=12, color=colour, line=dict(width=2))))


def _voronoi_layer(fig, las, view, colours, gap) -> None:
    from ldz_demand.geo import voronoi

    t = active()
    geo = voronoi.geojson()
    ids = [f["id"] for f in geo["features"]]
    common = dict(geojson=geo, featureidkey="id", locations=ids, hovertemplate="%{text}<extra></extra>")
    if view == "gap" and gap is not None:
        z = pd.Series(ids).map(gap).astype(float)
        fig.add_trace(go.Choropleth(
            **common, z=z, zmin=-GAP_RANGE, zmax=GAP_RANGE, colorscale=_gap_colourscale(t),
            text=[f"{i}: {v:+.2f} pp" for i, v in zip(ids, z)], marker=dict(line=dict(width=0.6, color=t.surface)),
            colorbar=dict(title=dict(text="pp"), outlinewidth=0, thickness=10, len=0.6)))
        return
    z, scale, n = _slots(pd.Series(ids), colours)
    fig.add_trace(go.Choropleth(
        **common, z=z, zmin=0, zmax=n, colorscale=scale, showscale=False, text=ids,
        marker=dict(opacity=0.85, line=dict(width=0.6, color=t.surface)), showlegend=False))


def _slots(ldz: pd.Series, colours: dict[str, str]):
    """Discrete colouring: each LDZ's colour slot as z, with a stepped colourscale."""
    palette = list(dict.fromkeys(colours.values()))
    z = ldz.map(lambda v: palette.index(colours[v]))
    n = max(len(palette) - 1, 1)
    scale = []
    for i, c in enumerate(palette):
        scale += [[max(0.0, (i - 0.5) / n), c], [min(1.0, (i + 0.5) / n), c]]
    return z, scale, n


def membership_check(las: pd.DataFrame, gas_use: pd.DataFrame, energy: pd.DataFrame | None,
                     methods=("authority", "voronoi")) -> pd.DataFrame:
    """
    Each LDZ's share of DESNZ annual gas use under each membership method (authorities split by vote
    share or by Voronoi area share), vs its share of measured National Gas demand (mean of the last
    three complete gas years). Columns: share_<method>, ng_share, gap_<method> (pp).
    """
    use = gas_use.set_index("lad24cd")["gwh_all"]
    out = pd.DataFrame(index=pd.Index(list(LDZS), name="ldz"))
    for method in methods:
        alloc = allocation(las, method).reindex(use.index).fillna(0.0)
        gwh = alloc.mul(use, axis=0).sum()
        out[f"share_{method}"] = 100 * gwh / gwh.sum()
    out["desnz_share"] = out[f"share_{methods[0]}"]  # kept for the single-method case
    if energy is not None:
        e = energy.reset_index()
        e = e[e["ldz"] != "GB"]
        end = pd.Timestamp(e["gas_day"].max())
        last_year_end = pd.Timestamp(year=end.year if end.month >= 10 else end.year - 1, month=10, day=1)
        e = e[(e["gas_day"] >= last_year_end - pd.DateOffset(years=3)) & (e["gas_day"] < last_year_end)]
        ng = e.groupby("ldz")["total_repaired"].sum() / 3
        out["ng_share"] = 100 * ng / ng.sum()
        for method in methods:
            out[f"gap_{method}"] = out[f"share_{method}"] - out["ng_share"]
        out["difference_pp"] = out[f"gap_{methods[0]}"]
    return out.reset_index().sort_values("ng_share" if energy is not None else "desnz_share")


def membership_check_chart(check: pd.DataFrame, methods=("authority", "voronoi")) -> go.Figure:
    """Each LDZ's share of GB gas: measured demand vs each membership method."""
    t = active()
    fig = go.Figure()
    for r in check.itertuples():
        xs = [getattr(r, f"share_{m}") for m in methods] + [r.ng_share]
        fig.add_trace(go.Scatter(x=[min(xs), max(xs)], y=[r.ldz, r.ldz], mode="lines",
                                 line=dict(color=t.axis, width=2), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=check["ng_share"], y=check["ldz"], mode="markers", name="National Gas demand (measured)",
                             marker=dict(size=11, color=t.ink, symbol="line-ns", line=dict(width=3, color=t.ink)),
                             hovertemplate="%{y}: %{x:.2f}% of measured demand<extra></extra>"))
    for i, m in enumerate(methods):
        mae = check[f"gap_{m}"].abs().mean()
        fig.add_trace(go.Scatter(
            x=check[f"share_{m}"], y=check["ldz"], mode="markers", name=f"{METHODS[m]} — mean |gap| {mae:.2f} pp",
            marker=dict(size=10, color=t.series[i], line=dict(width=2, color=t.surface)),
            customdata=check[f"gap_{m}"], hovertemplate="%{y}: %{x:.2f}% (%{customdata:+.2f} pp)<extra></extra>"))
    fig.update_layout(title="Each LDZ's share of GB gas: membership methods vs measured demand", xaxis_title="% of GB",
                      height=520, hovermode="closest", yaxis=dict(showgrid=False))
    return fig


def _key(las: pd.DataFrame) -> str:
    return json.dumps(sorted(zip(las["lad23cd"], las["main_ldz"])))
