"""
GB local authority boundaries (ONS, December 2023, ultra-generalised "BUC") for maps.

Shipped with the package as a small GeoJSON (Open Government Licence v3.0; contains OS data
© Crown copyright and database right 2023). Rings are rewound clockwise for Plotly, whose d3-geo
reads an anticlockwise ring as "the whole globe minus this shape". Rebuild with:

    python -m ldz_demand.geo fetch && python -m ldz_demand.geo build
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent / "data" / "lad23_buc_gb.geojson"
SERVICE = ("https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
           "Local_Authority_Districts_December_2023_Boundaries_UK_BUC/FeatureServer/0/query")
RAW_NAME = "lad23_buc_gb.geojson"
DECIMALS = 4
ATTRIBUTION = ("Source: Office for National Statistics licensed under the Open Government Licence v.3.0. "
               "Contains OS data © Crown copyright and database right 2023.")


def fetch(raw_dir: Path, session: requests.Session | None = None) -> Path:
    path = Path(raw_dir) / "reference" / "ons_lad" / RAW_NAME
    if path.exists():
        return path
    session = session or requests.Session()
    params = {"where": "LAD23CD NOT LIKE 'N%'", "outFields": "LAD23CD,LAD23NM", "outSR": "4326",
              "f": "geojson", "resultRecordCount": "2000"}
    response = session.get(SERVICE, params=params, timeout=300)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    logger.info(f"Fetched local authority boundaries -> {path}")
    return path


def build(raw_dir: Path, out: Path = DATA_FILE) -> Path:
    """Rewind rings clockwise, round coordinates, keep GB only."""
    from shapely.geometry import mapping, shape
    from shapely.geometry.polygon import orient

    raw = json.loads((Path(raw_dir) / "reference" / "ons_lad" / RAW_NAME).read_text())
    features = []
    for f in raw["features"]:
        geom = shape(f["geometry"])
        parts = getattr(geom, "geoms", [geom])
        clockwise = [orient(p, sign=-1.0) for p in parts]
        g = mapping(clockwise[0] if len(clockwise) == 1 else type(geom)(clockwise))
        features.append({"type": "Feature", "id": f["properties"]["LAD23CD"],
                         "properties": {"lad23cd": f["properties"]["LAD23CD"], "lad23nm": f["properties"]["LAD23NM"]},
                         "geometry": _round(g)})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "attribution": ATTRIBUTION, "features": features},
                              separators=(",", ":")))
    logger.info(f"Wrote {len(features)} boundaries -> {out} ({out.stat().st_size / 1024:.0f} KB)")
    return out


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(DATA_FILE.read_text())


def _round(geom: dict) -> dict:
    def r(c):
        return [round(c[0], DECIMALS), round(c[1], DECIMALS)] if isinstance(c[0], float) else [r(x) for x in c]
    return {"type": geom["type"], "coordinates": r(json.loads(json.dumps(geom["coordinates"])))}
