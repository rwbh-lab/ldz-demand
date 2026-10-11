"""
Charts for raw ERA5 weather: hourly gridded maps over GB for a single gas day.

The 0.25° ERA5 grid is too fine to label, so it is cropped to mainland GB and averaged into coarser
cells that are square on the ground (~110 or ~55 km): at GB's latitude a degree of longitude is only
~64 km, so cells span more longitude than latitude. Each cell is drawn as its true lat/lon box and
labelled with its value; a slider steps through the hours of the gas day (05:00 to 05:00 UK time).
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from ldz_demand.charts import coastline
from ldz_demand.charts.style import active
from ldz_demand.data.build.gas_day import gas_day_slice
from ldz_demand.data.ingest.era5 import load_hourly

ERA5_STEP = 0.25  # degrees
HEATING_THRESHOLD = 15.5  # °C — roughly where space heating switches on; the temperature midpoint
CELL_OPACITY = 0.6
# Mainland GB (Shetland, which has no gas network, is left out); edges sit on 0.25° grid points
DISPLAY_BOX = dict(north=59.5, south=49.75, west=-8.5, east=2.0)
CELL_SIZES = {"~110 km cells": 4, "~55 km cells": 2}  # latitude points (0.25° each) per cell


@dataclass(frozen=True)
class SampleDay:
    day: str
    label: str
    why: str


# Chosen from the 2021-09 → 2026-10 archive (England-box gas-day means; GB demand from National Gas).
SAMPLE_DAYS = (
    SampleDay("2022-12-15", "15 Dec 2022 — coldest day, peak demand",
              "The coldest gas day in the archive (England mean −1.9 °C) and the highest GB demand "
              "(~3,080 GWh). Light winds let the cold settle in under clear skies."),
    SampleDay("2026-01-05", "5 Jan 2026 — recent cold snap",
              "The most recent deep cold (England mean −1.6 °C) and the second-highest demand (~3,070 GWh)."),
    SampleDay("2024-01-20", "20 Jan 2024 — a typical January day",
              "A median January day (England mean 4.9 °C) — but breezy, which makes it feel colder: "
              "the reason the CWV blends wind with temperature."),
    SampleDay("2025-10-04", "4 Oct 2025 — Storm Amy",
              "The windiest gas day in the archive (GB-box mean wind 14 m/s). Mild, so demand stays "
              "low (~975 GWh) despite the wind."),
    SampleDay("2022-07-19", "19 Jul 2022 — record heat",
              "The UK's hottest day on record (40 °C measured in Lincolnshire; ERA5's 0.25° cells average "
              "lower). Gas demand at a summer low (~550 GWh)."),
)

VARIABLES = {
    "t2m": dict(label="Temperature", unit="°C", fmt="{:.0f}"),
    "ws10": dict(label="Wind speed (10 m)", unit="m/s", fmt="{:.0f}"),
}


def load_gas_day(raw_dir: Path, day: str):
    """Hourly ERA5 fields for one gas day (reads only the month files it needs)."""
    start = pd.Timestamp(day)
    months = (start.strftime("%Y-%m"), (start + pd.Timedelta(days=1)).strftime("%Y-%m"))
    return gas_day_slice(load_hourly(raw_dir, *months), day).load()


def crop(hourly, box: dict = DISPLAY_BOX):
    return hourly.sel(latitude=slice(box["north"], box["south"]), longitude=slice(box["west"], box["east"]))


def coarsen(hourly, lat_points: int):
    """
    Average lat_points x lon_points blocks of the 0.25° grid, with lon_points chosen so each cell is
    square on the ground at the grid's mean latitude. Partial blocks at the edges are dropped.
    """
    mean_lat = float(hourly["latitude"].mean())
    lon_points = max(1, int(round(lat_points / np.cos(np.radians(mean_lat)))))
    if lat_points <= 1 and lon_points <= 1:
        return hourly
    return hourly.coarsen(latitude=lat_points, longitude=lon_points, boundary="trim").mean()


def grid_map(hourly, variable: str = "t2m", lat_points: int = 4, title: str | None = None) -> go.Figure:
    """Hour-by-hour map of one variable: coloured, square-on-the-ground cells, each labelled with its value."""
    t = active()
    spec = VARIABLES[variable]
    grid = coarsen(crop(hourly), lat_points)[variable]
    lats, lons = grid["latitude"].values, grid["longitude"].values
    half_lat = abs(float(np.diff(lats).mean())) / 2 if len(lats) > 1 else ERA5_STEP / 2
    half_lon = abs(float(np.diff(lons).mean())) / 2 if len(lons) > 1 else ERA5_STEP / 2
    cells = [(la, lo) for la in lats for lo in lons]
    # Rings must run clockwise: Plotly's d3-geo reads an anticlockwise ring as "the globe minus this box"
    geojson = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": str(i), "properties": {},
         "geometry": {"type": "Polygon", "coordinates": [[
             [lo - half_lon, la - half_lat], [lo - half_lon, la + half_lat], [lo + half_lon, la + half_lat],
             [lo + half_lon, la - half_lat], [lo - half_lon, la - half_lat]]]}}
        for i, (la, lo) in enumerate(cells)
    ]}
    ids = [str(i) for i in range(len(cells))]
    cell_lat = [la for la, _ in cells]
    cell_lon = [lo for _, lo in cells]

    if variable == "t2m":
        # diverging around the heating threshold, equal arms; fixed across hours and days
        span = 25.0
        zmin, zmax = HEATING_THRESHOLD - span, HEATING_THRESHOLD + span
        stops = t.diverging
    else:
        # multi-hue, monotonic in lightness (inferno-style), like forecast wind maps
        zmin, zmax = 0.0, 20.0
        stops = t.wind
    colorscale = [[i / (len(stops) - 1), c] for i, c in enumerate(stops)]

    hours = pd.DatetimeIndex(grid["local_time"].values)
    frames = []
    for i, hour in enumerate(hours):
        z = grid.isel(time=i).values.ravel()
        frames.append(go.Frame(name=hour.strftime("%H:%M"), traces=[0, 2], data=[
            go.Choropleth(z=z),
            go.Scattergeo(text=[spec["fmt"].format(v) if np.isfinite(v) else "" for v in z],
                          textfont=dict(color=_text_colours(z, zmin, zmax, colorscale, t), size=_font_size(lat_points))),
        ]))

    first = frames[0].data
    coast_lon, coast_lat = coastline.load()
    fig = go.Figure(
        data=[
            go.Choropleth(
                geojson=geojson, locations=ids, featureidkey="id", z=first[0].z,
                zmin=zmin, zmax=zmax, colorscale=colorscale,
                # semi-transparent so the coastline (always drawn beneath data in Plotly) shows through
                marker=dict(line=dict(width=0), opacity=CELL_OPACITY),  # no cell borders: boxes abut
                colorbar=dict(title=dict(text=spec["unit"]), outlinewidth=0, thickness=10, len=0.75),
                customdata=np.stack([cell_lat, cell_lon], axis=1),
                hovertemplate=f"%{{customdata[0]:.2f}}°N %{{customdata[1]:.2f}}°E<br>%{{z:.1f}} {spec['unit']}<extra></extra>",
            ),
            # detailed coastline above the cells (Plotly's own is drawn beneath data) but below the
            # labels; frames only update traces 0 and 2, so it stays put while the hours animate
            go.Scattergeo(lon=coast_lon, lat=coast_lat, mode="lines", line=dict(color=t.ink, width=1.5),
                          hoverinfo="skip", showlegend=False),
            go.Scattergeo(lat=cell_lat, lon=cell_lon, mode="text", text=first[1].text,
                          textfont=first[1].textfont, hoverinfo="skip", showlegend=False),
        ],
        frames=frames,
    )
    south, north = float(lats.min()) - half_lat, float(lats.max()) + half_lat
    west, east = float(lons.min()) - half_lon, float(lons.max()) + half_lon
    fig.update_geos(
        # frame the map exactly to the grid, so no strip without values is shown. Plotly centres on the
        # mean latitude, which on a Mercator map sits too far south (top row clipped, gap at the bottom),
        # so centre on the Mercator midpoint instead.
        projection_type="mercator", resolution=50,
        lataxis_range=[south, north], lonaxis_range=[west, east],
        center=dict(lat=_mercator_mid(south, north), lon=(west + east) / 2),
        showland=True, landcolor=t.surface, showocean=True, oceancolor=t.page, showlakes=False,
        showcoastlines=False,  # replaced by the detailed coastline trace above
        showcountries=True, countrycolor=t.muted, bgcolor=t.surface, showframe=False,
    )
    steps = [dict(method="animate", label=f.name[:2],
                  args=[[f.name], dict(mode="immediate", frame=dict(duration=0, redraw=True), transition=dict(duration=0))])
             for f in frames]
    fig.update_layout(
        title=title or f"{spec['label']} — hour by hour (UK local time)",
        height=760, margin=dict(l=8, r=8, t=64, b=8),
        sliders=[dict(active=0, steps=steps, x=0.08, len=0.9, y=0.02, pad=dict(t=8),
                      currentvalue=dict(prefix="UK time ", suffix=":00", font=dict(color=t.ink, size=14)),
                      font=dict(color=t.ink_2), bgcolor=t.axis, activebgcolor=t.accent, bordercolor=t.axis,
                      tickcolor=t.muted)],
        updatemenus=[dict(type="buttons", direction="left", x=0.0, y=0.02, xanchor="left", yanchor="top",
                          pad=dict(t=8), bgcolor=t.surface, bordercolor=t.axis, font=dict(color=t.ink_2),
                          buttons=[dict(label="▶", method="animate",
                                        args=[None, dict(frame=dict(duration=600, redraw=True), fromcurrent=True,
                                                         transition=dict(duration=0))]),
                                   dict(label="❚❚", method="animate",
                                        args=[[None], dict(mode="immediate", frame=dict(duration=0, redraw=False))])])],
    )
    return fig


def day_summary(hourly) -> dict:
    """Headline numbers for a gas day: England-box temperature and GB-box wind."""
    eng = hourly.sel(latitude=slice(54.0, 50.5), longitude=slice(-3.0, 0.5))
    t_hourly = eng["t2m"].mean(["latitude", "longitude"])
    return {
        "t_mean": float(t_hourly.mean()),
        "t_min": float(t_hourly.min()),
        "t_max": float(t_hourly.max()),
        "ws_mean": float(hourly["ws10"].mean()),
        "ws_max": float(hourly["ws10"].max()),
        "hours": int(hourly.sizes["time"]),
    }


def _mercator_mid(south: float, north: float) -> float:
    """Latitude halfway between south and north on a Mercator map."""
    y = lambda lat: np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    return float(np.degrees(2 * np.arctan(np.exp((y(south) + y(north)) / 2)) - np.pi / 2))


def _text_colours(z, zmin, zmax, colorscale, t) -> list[str]:
    """Dark or light label per cell, whichever contrasts with the cell's fill."""
    pos = np.clip((np.nan_to_num(z, nan=zmin) - zmin) / (zmax - zmin), 0, 1)
    fills = sample_colorscale(colorscale, list(pos))
    return [t.page if _luminance(c) > 0.45 else t.ink for c in fills]


def _luminance(colour: str) -> float:
    if colour.startswith("#"):
        r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    else:
        r, g, b = (float(x) / 255 for x in colour[colour.index("(") + 1:colour.index(")")].split(",")[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _font_size(lat_points: int) -> int:
    return 12 if lat_points >= 4 else 9
