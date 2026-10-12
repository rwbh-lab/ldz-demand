"""
Hybrid LDZ map: local-authority labels where an authority is clearly in one LDZ, Voronoi cells only
inside split authorities.

The two pure methods fail in different places: Voronoi carves up London (its boroughs aren't listed
as towns), while whole-authority labels can't follow a boundary through an authority. The hybrid
keeps each method where it is strong:
- single-LDZ authorities (unanimous, majority or nearest-town) go wholly to their LDZ;
- a split authority is divided by the Voronoi cells, restricted to the LDZs its own towns voted for
  (so a neighbouring LDZ's cell can't add a third LDZ). If those cells don't reach any voting LDZ,
  the authority falls back to its vote shares.

Within a split authority the area is treated as uniform; weighting by where gas is used comes later.
"""

import json
from functools import lru_cache

import pandas as pd

from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.geo import boundaries, voronoi
from ldz_demand.geo.ldz_membership import read_table


@lru_cache(maxsize=1)
def authority_shares() -> pd.DataFrame:
    """Share of each local authority (rows: lad23cd) in each LDZ (columns)."""
    las = read_table("ldz_local_authority.csv").set_index("lad23cd")
    vor = voronoi.authority_shares()
    rows = {}
    for code, la in las.iterrows():
        if la["method"] != "split":
            rows[code] = {la["ldz"]: 1.0}
            continue
        votes = json.loads(la["votes"])
        inside = {ldz: vor.loc[code, ldz] for ldz in votes if vor.loc[code, ldz] > 0}
        source = inside if inside else votes
        total = sum(source.values())
        rows[code] = {ldz: w / total for ldz, w in source.items()}
    return pd.DataFrame.from_dict(rows, orient="index").reindex(columns=list(LDZS)).fillna(0.0)


@lru_cache(maxsize=1)
def ldz_polygons() -> dict:
    """{ldz: geometry}: whole single-LDZ authorities, plus each split authority cut by the Voronoi cells."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    las = read_table("ldz_local_authority.csv").set_index("lad23cd")
    vor_polys = voronoi.ldz_polygons()
    shares = authority_shares()
    pieces = {ldz: [] for ldz in LDZS}
    for f in boundaries.load()["features"]:
        code, geom = f["id"], shape(f["geometry"]).buffer(0)
        la = las.loc[code]
        if la["method"] != "split":
            pieces[la["ldz"]].append(geom)
            continue
        ldzs = [z for z in LDZS if shares.loc[code, z] > 0]
        cut = {z: geom.intersection(vor_polys[z]) for z in ldzs}
        if all(c.is_empty for c in cut.values()):
            pieces[la["main_ldz"]].append(geom)  # fallback to the vote shares: draw with the main LDZ
            continue
        # give any part of the authority outside the voting LDZs' cells to its nearest voting LDZ cell
        covered = unary_union([c for c in cut.values() if not c.is_empty])
        rest = geom.difference(covered)
        if not rest.is_empty:
            nearest = min((z for z in ldzs if not cut[z].is_empty), key=lambda z: rest.distance(cut[z]))
            cut[nearest] = cut[nearest].union(rest)
        for z, c in cut.items():
            if not c.is_empty:
                pieces[z].append(c)
    return {ldz: unary_union(p) for ldz, p in pieces.items()}


def geojson(decimals: int = 3) -> dict:
    """Hybrid LDZ polygons as GeoJSON for Plotly (rings clockwise, ids = LDZ codes)."""
    return voronoi.to_geojson(ldz_polygons(), decimals)
