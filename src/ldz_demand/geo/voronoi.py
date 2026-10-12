"""
The original quant-lib LDZ map method: a Voronoi cell around every listed town, merged into LDZs.

Kept as a comparison to the local-authority method. As in the original:
- each listed town gets the cell of all places closer to it than to any other town, computed in
  plain lon/lat degrees (the original did not project);
- a smoothing pass relabels a town's cell to the majority LDZ of its touching neighbours within
  SMOOTHING_DEG (ties keep the town's own LDZ), to clean up errors in the lists;
- cells are merged into one polygon per LDZ.
Differences, and why:
- town locations come from the ONS Index of Place Names (corrected names) instead of Nominatim
  geocoding, so the result is reproducible;
- the smoothing pass is order-independent (all relabels decided from the original labels), where
  the original updated labels in place while iterating;
- LDZ polygons are clipped to the GB coastline (the original's outer cells ran out to sea), and
  detached pieces such as islands are kept (the original kept only the largest piece).
"""

from collections import Counter
from functools import lru_cache

import numpy as np
import pandas as pd

from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.geo import boundaries
from ldz_demand.geo.ldz_membership import read_table

SMOOTHING_DEG = 0.3


def town_points(towns: pd.DataFrame | None = None) -> pd.DataFrame:
    """Placed towns used as Voronoi sites (outliers and unplaced towns excluded; one site per location)."""
    towns = read_table("ldz_towns.csv") if towns is None else towns
    placed = towns.dropna(subset=["lat"])
    placed = placed[~placed["method"].str.startswith("outlier")]
    return placed.drop_duplicates(subset=["lat", "lon"]).reset_index(drop=True)


def cells(points: pd.DataFrame, smoothing_deg: float = SMOOTHING_DEG) -> pd.DataFrame:
    """One Voronoi cell per town with its listed LDZ and its smoothed LDZ."""
    import shapely
    from shapely.geometry import MultiPoint, Point, box

    sites = [Point(lon, lat) for lon, lat in zip(points["lon"], points["lat"])]
    frame = box(-12, 47, 6, 64)
    regions = shapely.voronoi_polygons(MultiPoint(sites), extend_to=frame, ordered=True)
    polys = [shapely.intersection(p, frame) for p in regions.geoms]
    out = points[["ldz", "town", "lat", "lon"]].copy()
    out["cell"] = polys
    out["ldz_smoothed"] = _smooth(out, smoothing_deg) if smoothing_deg > 0 else out["ldz"]
    return out


def _smooth(c: pd.DataFrame, radius: float) -> list[str]:
    import shapely

    xy = c[["lon", "lat"]].to_numpy()
    tree = shapely.STRtree(list(c["cell"]))
    labels = c["ldz"].tolist()
    new = []
    for i, poly in enumerate(c["cell"]):
        touching = tree.query(poly, predicate="intersects")
        near = [j for j in touching if j != i and np.hypot(*(xy[j] - xy[i])) <= radius]
        if not near:
            new.append(labels[i])
            continue
        counts = Counter(labels[j] for j in near).most_common()
        tied = [ldz for ldz, n in counts if n == counts[0][1]]
        new.append(labels[i] if labels[i] in tied else tied[0])
    return new


@lru_cache(maxsize=4)
def ldz_polygons(smoothing_deg: float = SMOOTHING_DEG) -> dict:
    """{ldz: shapely geometry} — Voronoi cells merged per LDZ and clipped to the GB land outline."""
    from shapely.ops import unary_union

    c = cells(town_points(), smoothing_deg)
    land = gb_land()
    return {ldz: unary_union(list(c.loc[c["ldz_smoothed"] == ldz, "cell"])).intersection(land) for ldz in LDZS}


@lru_cache(maxsize=1)
def gb_land():
    """GB land outline: the union of all local authority boundaries."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    return unary_union([shape(f["geometry"]).buffer(0) for f in boundaries.load()["features"]])


@lru_cache(maxsize=4)
def authority_shares(smoothing_deg: float = SMOOTHING_DEG) -> pd.DataFrame:
    """Share of each local authority's area inside each Voronoi LDZ (rows: lad23cd; columns: LDZs)."""
    from shapely.geometry import shape

    polys = ldz_polygons(smoothing_deg)
    rows = {}
    for f in boundaries.load()["features"]:
        geom = shape(f["geometry"]).buffer(0)
        areas = {ldz: geom.intersection(p).area for ldz, p in polys.items()}
        total = sum(areas.values()) or 1.0
        rows[f["id"]] = {ldz: a / total for ldz, a in areas.items()}
    return pd.DataFrame.from_dict(rows, orient="index")[list(LDZS)]


def geojson(smoothing_deg: float = SMOOTHING_DEG, decimals: int = 3) -> dict:
    """The Voronoi LDZ polygons as GeoJSON for Plotly (rings clockwise, ids = LDZ codes)."""
    return to_geojson(ldz_polygons(smoothing_deg), decimals)


def to_geojson(polygons: dict, decimals: int = 3) -> dict:
    """{ldz: geometry} as Plotly-ready GeoJSON: polygons only, rings clockwise, ids = LDZ codes."""
    from shapely.geometry import mapping
    from shapely.geometry.polygon import orient

    features = []
    for ldz, geom in polygons.items():
        parts = [orient(p, sign=-1.0) for p in _polygons(geom)]
        coords = [mapping(p)["coordinates"] for p in parts]
        rounded = [[[[round(x, decimals), round(y, decimals)] for x, y in ring] for ring in poly] for poly in coords]
        features.append({"type": "Feature", "id": ldz, "properties": {"ldz": ldz},
                         "geometry": {"type": "MultiPolygon", "coordinates": rounded}})
    return {"type": "FeatureCollection", "features": features}


def _polygons(geom) -> list:
    """All non-empty Polygons inside a (Multi)Polygon or GeometryCollection."""
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [p for g in getattr(geom, "geoms", []) for p in _polygons(g)]
