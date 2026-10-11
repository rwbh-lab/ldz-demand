"""
Detailed GB coastline for map overlays.

Plotly's built-in coastlines are at most 1:50m and are always drawn beneath the data, so on the ERA5
maps they sit under the cells and don't stand out. Instead we draw the Natural Earth 1:10m coastline
(public domain) as a line trace on top. The clipped coastline ships with the package as a small JSON
file; rebuild it (needs cartopy, which downloads Natural Earth on first use) with:

    python -m ldz_demand.charts.coastline
"""

import json
import sys
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "gb_coastline_10m.json"
CLIP_BOX = dict(west=-9.0, south=49.0, east=2.5, north=60.0)  # a little larger than the map
DECIMALS = 4  # ~10 m; plenty at map scale


@lru_cache(maxsize=1)
def load() -> tuple[list, list]:
    """(lons, lats) for one Scattergeo line trace; separate coastline pieces are split by None."""
    pieces = json.loads(DATA_FILE.read_text())["pieces"]
    lons, lats = [], []
    for piece in pieces:
        lons += [p[0] for p in piece] + [None]
        lats += [p[1] for p in piece] + [None]
    return lons, lats


def build(path: Path = DATA_FILE) -> Path:
    import cartopy.io.shapereader as shapereader
    from shapely.geometry import box

    source = shapereader.natural_earth(resolution="10m", category="physical", name="coastline")
    clip = box(CLIP_BOX["west"], CLIP_BOX["south"], CLIP_BOX["east"], CLIP_BOX["north"])
    pieces = []
    for record in shapereader.Reader(source).records():
        geom = record.geometry
        if not geom.intersects(clip):
            continue
        clipped = geom.intersection(clip)
        for part in getattr(clipped, "geoms", [clipped]):
            coords = [[round(x, DECIMALS), round(y, DECIMALS)] for x, y in part.coords]
            if len(coords) >= 2:
                pieces.append(coords)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source": "Natural Earth 1:10m coastline (public domain), naturalearthdata.com",
        "clip_box": CLIP_BOX,
        "pieces": pieces,
    }, separators=(",", ":")))
    return path


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KB, {len(json.loads(out.read_text())['pieces'])} pieces)")
    sys.exit(0)
