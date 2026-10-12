"""
ERA5 grid-cell weights per LDZ: how much each 0.25° cell counts towards each LDZ's weather.

LDZ weather is a weighted mean of grid cells, so each variant is a set of weights:

- membership — which places belong to the LDZ, one per map method (authority, voronoi, hybrid,
  sampled; see ldz_demand.charts.geography.METHODS);
- weighting — how the places inside the LDZ are weighted:
  - area: every km² of land equally (the land mean);
  - gas: each authority's DESNZ annual gas use, spread evenly over its area.

The weight of a cell is the sum, over the pieces of land it contains, of area × LDZ share × density:
- authority and sampled methods give shares per authority, so a cell inside a split authority counts
  towards each of its LDZs by that authority's shares (uniform within the authority);
- voronoi and hybrid give LDZ polygons, so pieces are cut by the polygons too, keeping the
  geography inside split authorities.

Plus the official reference: membership "station", weighting "point" — the one weather station each
LDZ's CWV uses (cwv_stations.csv), bilinearly interpolated from the four surrounding grid points.

Each grid point is the centre of its cell; weights sum to 1 per (membership, weighting, variable, ldz).

Output: geo/data/ldz_cell_weights.csv (committed; no ERA5 data needed to build it).
"""

import logging
from functools import lru_cache

import numpy as np
import pandas as pd

from ldz_demand.config import create_config
from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.geo import boundaries
from ldz_demand.geo.ldz_membership import DATA_DIR, read_table, vote_shares

logger = logging.getLogger(__name__)

GRID_STEP = 0.25
MEMBERSHIPS = ("authority", "voronoi", "hybrid", "sampled")
WEIGHTINGS = ("area", "gas")
KM_PER_DEG = 111.32
OUTPUT = "ldz_cell_weights.csv"
COLUMNS = ["membership", "weighting", "variable", "ldz", "lat", "lon", "weight"]

HEADER = (
    "# Derived by ldz-demand (python -m ldz_demand.geo build). ERA5 0.25° grid-cell weights per LDZ, from the LDZ\n"
    "# membership tables, ONS local authority boundaries (contains OS data © Crown copyright and database right 2023)\n"
    "# and DESNZ subnational gas consumption 2024 (Open Government Licence v3.0). Station locations: see cwv_stations.csv.\n"
)


def era5_grid(area=None) -> tuple[np.ndarray, np.ndarray]:
    """(lats, lons) of the ERA5 grid points for the configured [era5] area (north, west, south, east)."""
    if area is None:
        area = [float(x) for x in create_config()["era5"]["area"].split(",")]
    north, west, south, east = area
    lats = np.round(np.arange(north, south - 1e-9, -GRID_STEP), 2)
    lons = np.round(np.arange(west, east + 1e-9, GRID_STEP), 2)
    return lats, lons


def _cells(lats, lons):
    from shapely.geometry import box

    h = GRID_STEP / 2
    keys = [(la, lo) for la in lats for lo in lons]
    return keys, [box(lo - h, la - h, lo + h, la + h) for la, lo in keys]


def _km2(geom, lat: float) -> float:
    return geom.area * KM_PER_DEG ** 2 * np.cos(np.radians(lat))


def _land_pieces(geom, tree, keys, polys) -> list[tuple[float, float, float]]:
    """(lat, lon, km²) of geom inside each grid cell."""
    out = []
    for i in tree.query(geom, predicate="intersects"):
        piece = geom.intersection(polys[i])
        if not piece.is_empty:
            lat, lon = keys[i]
            out.append((lat, lon, _km2(piece, lat)))
    return out


def pieces(membership: str, lats=None, lons=None) -> pd.DataFrame:
    """Land pieces for one membership method: lad23cd, ldz, lat, lon, km2, share."""
    import shapely
    from shapely.geometry import shape

    from ldz_demand.geo import hybrid, postcode_sample, voronoi

    if lats is None:
        lats, lons = era5_grid()
    keys, polys = _cells(lats, lons)
    tree = shapely.STRtree(polys)
    las = read_table("ldz_local_authority.csv")
    if membership in ("voronoi", "hybrid"):
        shares = (voronoi if membership == "voronoi" else hybrid).authority_shares()
        ldz_polys = (voronoi if membership == "voronoi" else hybrid).ldz_polygons()
    elif membership == "sampled":
        shares, ldz_polys = postcode_sample.authority_shares(), None
    elif membership == "authority":
        shares, ldz_polys = vote_shares(las), None
    else:
        raise ValueError(f"unknown membership {membership!r}")

    rows = []
    for f in boundaries.load()["features"]:
        code, geom = f["id"], shape(f["geometry"]).buffer(0)
        s = shares.loc[code]
        for ldz in s.index[s > 0]:
            if ldz_polys is None:  # shares per authority, uniform inside it
                rows += [(code, ldz, la, lo, a, s[ldz]) for la, lo, a in _land_pieces(geom, tree, keys, polys)]
            else:                  # cut by the method's LDZ polygons
                part = geom.intersection(ldz_polys[ldz])
                rows += [(code, ldz, la, lo, a, 1.0) for la, lo, a in _land_pieces(part, tree, keys, polys)]
    return pd.DataFrame(rows, columns=["lad23cd", "ldz", "lat", "lon", "km2", "share"])


def density(weighting: str) -> pd.Series:
    """Weight per km² of each authority (index lad23cd)."""
    from shapely.geometry import shape

    from ldz_demand.geo import gas_use

    las = read_table("ldz_local_authority.csv").set_index("lad23cd")
    if weighting == "area":
        return pd.Series(1.0, index=las.index)
    if weighting == "gas":
        use = gas_use.load().set_index("lad24cd")["gwh_all"]
        areas = {}
        for f in boundaries.load()["features"]:
            geom = shape(f["geometry"]).buffer(0)
            areas[f["id"]] = _km2(geom, geom.centroid.y)
        return pd.Series({code: use.get(las.loc[code, "lad24cd"], 0.0) / areas[code] for code in las.index})
    raise ValueError(f"unknown weighting {weighting!r}")


def weights_from_pieces(p: pd.DataFrame, dens: pd.Series) -> pd.DataFrame:
    """Cell weights per LDZ (summing to 1 per LDZ) from land pieces and a density per authority."""
    w = p.assign(weight=p["km2"] * p["share"] * p["lad23cd"].map(dens).fillna(0.0))
    w = w.groupby(["ldz", "lat", "lon"], as_index=False)["weight"].sum()
    w = w[w["weight"] > 0]
    w["weight"] = w["weight"] / w.groupby("ldz")["weight"].transform("sum")
    return w


def bilinear(lat: float, lon: float, lats, lons) -> list[tuple[float, float, float]]:
    """(lat, lon, weight) of the four grid points around a location."""
    lat0 = np.floor(lat / GRID_STEP) * GRID_STEP
    lon0 = np.floor(lon / GRID_STEP) * GRID_STEP
    fy, fx = (lat - lat0) / GRID_STEP, (lon - lon0) / GRID_STEP
    out = []
    for dy, wy in ((0, 1 - fy), (1, fy)):
        for dx, wx in ((0, 1 - fx), (1, fx)):
            la, lo = round(lat0 + dy * GRID_STEP, 2), round(lon0 + dx * GRID_STEP, 2)
            if wy * wx > 0:
                if la not in lats or lo not in lons:
                    raise ValueError(f"station at {lat}, {lon} is outside the ERA5 grid")
                out.append((la, lo, wy * wx))
    return out


def station_weights(lats=None, lons=None) -> pd.DataFrame:
    """The official one-station-per-LDZ reference, per variable (t2m, ws10)."""
    if lats is None:
        lats, lons = era5_grid()
    stations = read_table("cwv_stations.csv")
    rows = []
    for s in stations.itertuples():
        for variable in (("t2m", "ws10") if s.variable == "all" else (s.variable,)):
            rows += [("station", "point", variable, s.ldz, la, lo, w) for la, lo, w in bilinear(s.lat, s.lon, list(lats), list(lons))]
    return pd.DataFrame(rows, columns=COLUMNS)


def build(raw_dir=None, out_dir=DATA_DIR) -> pd.DataFrame:
    """All variants -> geo/data/ldz_cell_weights.csv. (raw_dir unused: built from committed tables.)"""
    lats, lons = era5_grid()
    frames = [station_weights(lats, lons)]
    dens = {w: density(w) for w in WEIGHTINGS}
    for membership in MEMBERSHIPS:
        p = pieces(membership, lats, lons)
        for weighting in WEIGHTINGS:
            for variable in ("t2m", "ws10"):
                w = weights_from_pieces(p, dens[weighting])
                frames.append(w.assign(membership=membership, weighting=weighting, variable=variable)[COLUMNS])
        logger.info(f"Cell weights: {membership} done")
    out = pd.concat(frames, ignore_index=True)
    out["weight"] = out["weight"].round(8)
    with open(out_dir / OUTPUT, "w", newline="") as f:
        f.write(HEADER)
        out.to_csv(f, index=False)
    logger.info(f"Cell weights: {len(out)} rows -> {out_dir / OUTPUT}")
    return out


def fetch(raw_dir=None) -> None:
    """Nothing to fetch: built from committed tables."""


@lru_cache(maxsize=1)
def load() -> pd.DataFrame:
    return read_table(OUTPUT)


def variants(weights: pd.DataFrame | None = None) -> list[tuple[str, str]]:
    """(membership, weighting) pairs in the table, station first."""
    weights = load() if weights is None else weights
    pairs = weights[["membership", "weighting"]].drop_duplicates()
    return sorted(map(tuple, pairs.to_numpy()), key=lambda mw: (mw[0] != "station",) + mw)
