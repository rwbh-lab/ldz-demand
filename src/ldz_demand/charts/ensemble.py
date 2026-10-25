"""
Charts for the ECMWF ensemble per LDZ: forecast fans, asymmetry, and where the uncertainty is.

One run is a cube of member values: (variant, variable, ldz, member, lead day), from ens_ldz_daily.
GB is added as a gas-use-weighted average of the LDZs. The 50 members are equally likely, so the
spread is read from member quantiles: the middle 50% (P25-P75) and 80% (P10-P90) around the median.

Asymmetry compares the two sides of the spread: the lower arm (median - P10) and the upper arm
(P90 - median); Kelly's skewness (P90 + P10 - 2 P50) / (P90 - P10) puts it on a -1..1 scale
(negative: a long lower tail — for temperature, a cold tail). Because the spread grows with lead time,
the arms can also be measured from the mean in standard deviations of the members: for a symmetric
bell-shaped spread both are NORMAL_ARM (1.28), so any difference is lopsidedness, whatever the spread.
"""

from functools import lru_cache

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import xarray as xr

from ldz_demand.charts.style import active, chart_bg
from ldz_demand.data.ingest.national_gas import LDZS

GB = "GB"
VARIABLES = {  # name -> (label, unit, lower / upper side names)
    "t2m": ("Temperature (gas-day mean)", "°C", ("cold", "warm")),
    "tmin": ("Lowest temperature", "°C", ("cold", "warm")),
    "tmax": ("Highest temperature", "°C", ("cold", "warm")),
    "ws10": ("Wind speed", "m/s", ("calm", "windy")),
    "ssrd": ("Solar radiation", "W/m²", ("dull", "sunny")),
    "tp": ("Precipitation", "mm", ("dry", "wet")),
}
VARIANT_LABELS = {("sampled", "gas"): "Sampled · gas use", ("station", "point"): "Station (official CWV)"}
REFERENCE = ("sampled", "gas")
NORMAL_ARM = 1.2816  # P90 of a normal distribution, in standard deviations from the mean


# --- data -----------------------------------------------------------------------------------------

def cube(rows: pd.DataFrame) -> xr.DataArray:
    """ens_ldz_daily rows for one run -> DataArray (variant, variable, ldz, member, lead)."""
    r = rows.assign(variant=rows["membership"] + "/" + rows["weighting"])
    da = r.set_index(["variant", "variable", "ldz", "member", "lead_days"])["value"].to_xarray()
    return da.rename(lead_days="lead")


def with_gb(da: xr.DataArray, shares: pd.Series) -> xr.DataArray:
    """Add GB: the LDZs weighted by their share of gas use (shares indexed by LDZ, summing to 1)."""
    w = xr.DataArray(shares.reindex(da["ldz"].values).fillna(0).to_numpy(), dims="ldz", coords={"ldz": da["ldz"]})
    gb = (da * w).sum("ldz", min_count=1) / w.where(da.notnull()).sum("ldz")
    return xr.concat([gb.expand_dims(ldz=[GB]), da], dim="ldz")


@lru_cache(maxsize=1)
def gas_shares() -> pd.Series:
    """Each LDZ's share of GB gas use (DESNZ, sampled membership), for the GB average."""
    from ldz_demand.charts.geography import allocation
    from ldz_demand.geo import gas_use
    from ldz_demand.geo.ldz_membership import read_table

    use = gas_use.load().set_index("lad24cd")["gwh_all"]
    alloc = allocation(read_table("ldz_local_authority.csv"), "sampled").reindex(use.index).fillna(0.0)
    gwh = alloc.mul(use, axis=0).sum()
    return gwh / gwh.sum()


def quantiles(members: xr.DataArray, qs=(0.1, 0.25, 0.5, 0.75, 0.9)) -> xr.DataArray:
    """Member quantiles along 'member' (dims: quantile, ...)."""
    return members.quantile(list(qs), dim="member", skipna=True)


def asymmetry(members: xr.DataArray) -> pd.DataFrame:
    """
    Per lead day: lower / upper arms from the median (P50 - P10, P90 - P50), Kelly skewness, IQR; and
    the arms from the mean in standard deviations (lower_sd, upper_sd: NORMAL_ARM each if symmetric).
    """
    q = quantiles(members)
    p10, p25, p50, p75, p90 = (q.sel(quantile=v).values for v in (0.1, 0.25, 0.5, 0.75, 0.9))
    mean, sd = members.mean("member").values, members.std("member", ddof=1).values
    width = p90 - p10
    with np.errstate(invalid="ignore", divide="ignore"):
        kelly = np.where(width > 0, (p90 + p10 - 2 * p50) / width, 0.0)
        lower_sd = np.where(sd > 0, (mean - p10) / sd, np.nan)
        upper_sd = np.where(sd > 0, (p90 - mean) / sd, np.nan)
    return pd.DataFrame({"lower": p50 - p10, "upper": p90 - p50, "kelly": kelly, "iqr": p75 - p25,
                         "median": p50, "mean": mean, "sd": sd, "lower_sd": lower_sd, "upper_sd": upper_sd},
                        index=pd.Index(members["lead"].values, name="lead"))


# --- charts ---------------------------------------------------------------------------------------

def _alpha(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _days(run_date, leads) -> list[str]:
    start = pd.Timestamp(run_date)
    return [f"{(start + pd.Timedelta(days=int(k))):%a %d %b}" for k in leads]


def fan_chart(da: xr.DataArray, run_date, ldz: str, variable: str, variant=REFERENCE,
              compare=None, show_members: bool = False) -> go.Figure:
    """The forecast fan for one LDZ: P10-P90 and P25-P75 bands, median and mean, optional members."""
    t = active()
    label, unit, _ = VARIABLES[variable]
    members = da.sel(variant="/".join(variant), variable=variable, ldz=ldz)
    leads = members["lead"].values
    days = _days(run_date, leads)
    q = quantiles(members)
    colour = t.series[0]
    fig = go.Figure()
    if show_members:
        for m in members["member"].values:
            fig.add_trace(go.Scatter(x=leads, y=members.sel(member=m).values, mode="lines", showlegend=False,
                                     line=dict(color=_alpha(t.muted, 0.35), width=1), hoverinfo="skip"))
    for lo, hi, alpha, name in ((0.1, 0.9, 0.18, "P10–P90 (80% of members)"), (0.25, 0.75, 0.35, "P25–P75 (50%)")):
        fig.add_trace(go.Scatter(x=leads, y=q.sel(quantile=hi).values, mode="lines", line=dict(width=0),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=leads, y=q.sel(quantile=lo).values, mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor=_alpha(colour, alpha), name=name, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=leads, y=q.sel(quantile=0.5).values, mode="lines", name="Median",
                             line=dict(color=colour, width=2.5), customdata=days,
                             hovertemplate=f"%{{customdata}} (day %{{x}}): median %{{y:.1f}} {unit}<extra></extra>"))
    fig.add_trace(go.Scatter(x=leads, y=members.mean("member").values, mode="lines", name="Mean",
                             line=dict(color=t.ink, width=1.5, dash="dot"),
                             hovertemplate=f"mean %{{y:.1f}} {unit}<extra></extra>"))
    if compare is not None:
        other = da.sel(variant="/".join(compare), variable=variable, ldz=ldz)
        oq = quantiles(other)
        c2 = t.series[4]
        for qq, dash, name in ((0.5, "solid", f"{VARIANT_LABELS.get(tuple(compare), compare)}: median"),
                               (0.25, "dash", "… P25 / P75"), (0.75, "dash", None)):
            fig.add_trace(go.Scatter(x=leads, y=oq.sel(quantile=qq).values, mode="lines", name=name,
                                     showlegend=name is not None, line=dict(color=c2, width=1.5, dash=dash),
                                     hovertemplate=f"station P{int(qq * 100)} %{{y:.1f}} {unit}<extra></extra>"))
    fig.update_layout(
        title=f"{ldz}: {label.lower()} — run of {pd.Timestamp(run_date):%d %b %Y}",
        xaxis=dict(title="Lead day (0 = the run's own gas day)", tickmode="array", tickvals=leads,
                   ticktext=[f"{k}<br>{d[:6]}" for k, d in zip(leads, days)]),
        yaxis_title=unit, height=460, hovermode="x unified", margin=dict(t=64, b=110),
        legend=dict(orientation="h", x=0, xanchor="left", y=-0.25, yanchor="top"))
    return fig


def asymmetry_chart(da: xr.DataArray, run_date, ldz: str, variable: str, variant=REFERENCE,
                    scale: str = "units") -> go.Figure:
    """
    The two sides of the spread per lead day, side by side. scale "units": P50 - P10 and P90 - P50 in the
    variable's units (shows the spread growing); "sd": mean - P10 and P90 - mean in standard deviations
    of the members (the growth divided out, so only lopsidedness remains; symmetric = NORMAL_ARM each).
    """
    t = active()
    label, unit, (low_name, high_name) = VARIABLES[variable]
    a = asymmetry(da.sel(variant="/".join(variant), variable=variable, ldz=ldz))
    days = _days(run_date, a.index)
    cold, warm = t.diverging[1], t.diverging[-2]
    if scale == "sd":
        lower, upper, centre, u = a["lower_sd"], a["upper_sd"], "mean", "SD"
        fmt = f"%{{customdata[0]:.2f}} SD (%{{customdata[3]:.2f}} {unit})"
        raw_lower, raw_upper = a["mean"] - (a["median"] - a["lower"]), (a["median"] + a["upper"]) - a["mean"]
    else:
        lower, upper, centre, u = a["lower"], a["upper"], "median", unit
        fmt = f"%{{customdata[0]:.2f}} {unit}"
        raw_lower, raw_upper = a["lower"], a["upper"]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=a.index, x=-lower, orientation="h", name=f"{low_name.title()} side ({centre} to P10)",
                         marker=dict(color=cold), customdata=np.stack([lower, a["kelly"], days, raw_lower], axis=1),
                         hovertemplate=f"%{{customdata[2]}}: {low_name} side {fmt}<extra></extra>"))
    fig.add_trace(go.Bar(y=a.index, x=upper, orientation="h", name=f"{high_name.title()} side ({centre} to P90)",
                         marker=dict(color=warm), customdata=np.stack([upper, a["kelly"], days, raw_upper], axis=1),
                         hovertemplate=(f"%{{customdata[2]}}: {high_name} side {fmt}"
                                        "<br>Kelly skewness %{customdata[1]:.2f}<extra></extra>")))
    top = float(np.nanmax(np.r_[lower.to_numpy(), upper.to_numpy(), NORMAL_ARM if scale == "sd" else 0.1])) * 1.1
    if scale == "sd":
        for x in (-NORMAL_ARM, NORMAL_ARM):
            fig.add_vline(x=x, line=dict(color=t.muted, width=1, dash="dash"))
        fig.add_annotation(x=NORMAL_ARM, y=1.0, yref="paper", yanchor="bottom", showarrow=False,
                           text="symmetric (1.28)", font=dict(color=t.ink_2, size=11))
    title = (f"{ldz}: lopsidedness, spread growth removed — {label.lower()}" if scale == "sd"
             else f"{ldz}: spread either side of the median — {label.lower()}")
    fig.update_layout(
        title=title,
        barmode="overlay", height=480, margin=dict(t=72, b=90),
        xaxis=dict(title=f"{u} from the {centre}", range=[-top, top], zeroline=True, zerolinecolor=t.axis),
        yaxis=dict(title="Lead day", autorange="reversed", tickmode="array", tickvals=list(a.index),
                   ticktext=[f"{k}  {d[:6]}" for k, d in zip(a.index, days)]),
        legend=dict(orientation="h", x=0, xanchor="left", y=-0.14, yanchor="top"))
    return fig


def members_strip(da: xr.DataArray, run_date, ldz: str, variable: str, lead: int, variant=REFERENCE) -> go.Figure:
    """Every member on one lead day, with the quartiles and P10 / P90 marked."""
    t = active()
    label, unit, _ = VARIABLES[variable]
    v = da.sel(variant="/".join(variant), variable=variable, ldz=ldz, lead=lead).dropna("member")
    values = np.sort(v.values)
    rng = np.random.default_rng(lead)
    jitter = rng.uniform(-0.3, 0.3, len(values))
    q = np.quantile(values, [0.1, 0.25, 0.5, 0.75, 0.9]) if len(values) else [np.nan] * 5
    fig = go.Figure()
    for x, name, dash in ((q[0], "P10", "dot"), (q[1], "P25", "dash"), (q[2], "Median", "solid"),
                          (q[3], "P75", "dash"), (q[4], "P90", "dot")):
        fig.add_vline(x=x, line=dict(color=t.muted if name != "Median" else t.ink, width=1.5, dash=dash),
                      annotation_text=name, annotation_position="top", annotation_font_color=t.ink_2)
    fig.add_trace(go.Scatter(x=values, y=jitter, mode="markers", name="Members",
                             marker=dict(size=9, color=t.series[0], line=dict(width=1, color=t.surface)),
                             hovertemplate=f"%{{x:.2f}} {unit}<extra></extra>", showlegend=False))
    day = _days(run_date, [lead])[0]
    fig.update_layout(title=f"{ldz}: all {len(values)} members, lead day {lead} ({day})",
                      xaxis_title=unit, yaxis=dict(visible=False, range=[-1, 1]), height=260, margin=dict(t=80, b=48))
    return fig


def spread_heatmap(da: xr.DataArray, run_date, variable: str, measure: str = "iqr", variant=REFERENCE) -> go.Figure:
    """LDZ x lead day, coloured by the spread (IQR) or by Kelly skewness."""
    t = active()
    label, unit, (low_name, high_name) = VARIABLES[variable]
    sub = da.sel(variant="/".join(variant), variable=variable)
    ldzs = [z for z in [GB, *LDZS] if z in sub["ldz"].values]
    table = pd.DataFrame({z: asymmetry(sub.sel(ldz=z))[measure] for z in ldzs}).T
    leads = list(table.columns)
    days = _days(run_date, leads)
    if measure == "kelly":
        stops = t.diverging
        scale = [[i / (len(stops) - 1), c] for i, c in enumerate(stops)]
        z_kw = dict(zmin=-1, zmax=1, zmid=0)
        title = f"Lopsidedness by LDZ and lead day (below 0: longer {low_name} tail)"
        bar = "skewness"
    else:
        stops = t.sequential
        scale = [[i / (len(stops) - 1), c] for i, c in enumerate(stops)]
        z_kw = dict(zmin=0)
        title = f"Spread (P25–P75) by LDZ and lead day — {label.lower()}"
        bar = unit
    values = table.to_numpy(dtype=float)
    hover = np.array([[f"{z}, day {k} ({d}): {'no data' if np.isnan(v) else f'{v:+.2f}' if measure == 'kelly' else f'{v:.2f} {unit}'}"
                       for k, d, v in zip(leads, days, row)] for z, row in zip(table.index, values)], dtype=object)
    fig = go.Figure(go.Heatmap(
        z=values, x=leads, y=table.index, colorscale=scale, **z_kw, xgap=2, ygap=2,
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
        colorbar=dict(title=dict(text=bar), outlinewidth=0, thickness=10, len=0.7)))
    fig.update_layout(title=title, height=520, margin=dict(t=64, b=48),
                      xaxis=dict(title="Lead day", tickmode="array", tickvals=leads),
                      yaxis=dict(autorange="reversed"))
    return fig


def station_gap(da: xr.DataArray, ldz: str, variable: str, reference=REFERENCE) -> pd.Series:
    """Per lead day: the station forecast's median minus the reference's median (the forecast's view of the gap)."""
    station = da.sel(variant="station/point", variable=variable, ldz=ldz).median("member")
    ours = da.sel(variant="/".join(reference), variable=variable, ldz=ldz).median("member")
    return (station - ours).to_series()


@lru_cache(maxsize=8)
def usual_station_gaps(variable: str) -> pd.DataFrame:
    """
    ERA5's station-minus-reference gap by LDZ and month (weather_ldz_daily): one read for every LDZ,
    the first time it is needed, then kept. Only the station and sampled variants are read.
    """
    from ldz_demand.charts.weather_ldz import station_offsets
    from ldz_demand.config import create_config
    from ldz_demand.data.datasets import WEATHER_LDZ_DAILY
    from ldz_demand.data.store import get_store

    rows = get_store(create_config()).read(WEATHER_LDZ_DAILY, variable=variable, membership=["station", "sampled"])
    return station_offsets(rows, variable)


def station_gap_note(forecast_gap: pd.Series, offsets: pd.DataFrame, run_date, ldz: str, variable: str) -> str:
    """
    One line putting this run's station gap in context: the forecast's average gap over the lead days,
    against the typical gap for this LDZ and month in ERA5 (offsets: weather_ldz.station_offsets output).
    """
    from ldz_demand.charts.weather_ldz import MONTH_NAMES

    unit = VARIABLES[variable][1]
    month = pd.Timestamp(run_date).month
    usual = offsets[(offsets["ldz"] == ldz) & (offsets["month"] == month)] if len(offsets) else offsets
    gap = float(forecast_gap.mean())
    if usual.empty:
        return f"This run: the station reads {gap:+.2f} {unit} against our gas-weighted {ldz} on average."
    mean, sd = float(usual["mean"].iloc[0]), float(usual["sd"].iloc[0])
    usual_gap = abs(gap - mean) <= max(2 * sd / 3, 0.15)
    context = (f"about what ERA5 shows for this station in this month: a steady gap from where the station is, not "
               f"from the forecast (see *LDZ weather* §4)." if usual_gap else
               f"{'larger' if abs(gap) > abs(mean) else 'smaller'} than usual for this station in this month: "
               f"the weather pattern in this run (e.g. wind direction, cloud) is changing how the station compares.")
    return (f"This run: the station reads **{gap:+.2f} {unit}** against our gas-weighted {ldz} on average over the "
            f"15 days. In ERA5 since 2021, the {MONTH_NAMES[month]} average is **{mean:+.2f} {unit}** (day to day "
            f"±{sd:.2f}) — {context}")


# --- the map ----------------------------------------------------------------------------------------

MAP_LEADS = range(0, 14)          # lead days 0–13: the days the run covers in full
MAP_MIN_SPAN = 3.0                # °C: the colour scale spans at least this either side of its centre


def mean_map(da: xr.DataArray, run_date, variable: str = "t2m") -> go.Figure:
    """
    The ensemble mean per LDZ (gas-weighted), lead day by lead day: each LDZ coloured by its mean and
    labelled with it; a slider (and play button) steps through the run's 14 days. Hover gives P10–P90.
    """
    from ldz_demand.charts import coastline, geography
    from ldz_demand.charts.era5 import HEATING_THRESHOLD, _mercator_mid
    from ldz_demand.geo import boundaries
    from ldz_demand.geo.ldz_membership import read_table

    t = active()
    las = read_table("ldz_local_authority.csv")
    _, labels = geography._ldz_shapes(geography._key(las))
    v = da.sel(variant="/".join(REFERENCE), variable=variable).sel(ldz=list(LDZS))
    leads = [lead for lead in MAP_LEADS if lead in v["lead"].values]
    mean = v.mean("member").to_pandas()                                  # ldz x lead
    p10, p90 = (v.quantile(q, "member").drop_vars("quantile").to_pandas() for q in (0.1, 0.9))
    label, unit, _ = VARIABLES[variable]
    centre = HEATING_THRESHOLD if variable == "t2m" else float(np.nanmean(mean.values))
    # sized to this run (all 14 days on one scale), so differences between days and LDZs show
    span = max(MAP_MIN_SPAN, float(np.ceil(np.nanmax(np.abs(mean[leads].values - centre)))))
    stops = t.diverging
    colorscale = [[i / (len(stops) - 1), c] for i, c in enumerate(stops)]
    run = pd.Timestamp(run_date)

    def layers(lead):
        z = las["main_ldz"].map(mean[lead]).astype(float)
        hover = [f"{ldz} · {run + pd.Timedelta(days=lead):%a %d %b}<br>mean {mean.at[ldz, lead]:.1f} {unit} "
                 f"(10–90%: {p10.at[ldz, lead]:.1f} – {p90.at[ldz, lead]:.1f})" for ldz in las["main_ldz"]]
        text = [f"{ldz}<br>{mean.at[ldz, lead]:.1f}°" if unit == "°C" else f"{ldz}<br>{mean.at[ldz, lead]:.1f}"
                for ldz in LDZS]
        return z, hover, text

    z0, hover0, text0 = layers(leads[0])
    coast_lon, coast_lat = coastline.load()
    fig = go.Figure(
        data=[
            go.Choropleth(geojson=boundaries.load(), featureidkey="id", locations=las["lad23cd"], z=z0, text=hover0,
                          zmin=centre - span, zmax=centre + span, colorscale=colorscale,
                          marker=dict(line=dict(width=0.2, color=t.surface)),
                          colorbar=dict(title=dict(text=unit), outlinewidth=0, thickness=10, len=0.6),
                          hovertemplate="%{text}<extra></extra>"),
            go.Scattergeo(lon=coast_lon, lat=coast_lat, mode="lines", line=dict(color=t.ink_2, width=1),
                          hoverinfo="skip", showlegend=False),
            go.Scattergeo(lon=[labels[z][1] for z in LDZS], lat=[labels[z][0] for z in LDZS], text=text0, mode="text",
                          textfont=dict(color=t.ink, size=13, family=t.font), hoverinfo="skip", showlegend=False),
        ],
        frames=[go.Frame(name=str(lead), traces=[0, 2],
                         data=[go.Choropleth(z=z, text=hover), go.Scattergeo(text=text)])
                for lead, (z, hover, text) in ((lead, layers(lead)) for lead in leads)],
    )
    south, north, west, east = 49.85, 59.0, -8.2, 1.9
    fig.update_geos(projection_type="mercator", resolution=50, lataxis_range=[south, north], lonaxis_range=[west, east],
                    center=dict(lat=_mercator_mid(south, north), lon=(west + east) / 2), showland=True,
                    landcolor=t.surface, showocean=True, oceancolor=t.page, showcoastlines=False, showcountries=False,
                    showlakes=False, bgcolor=chart_bg(t), showframe=False)
    steps = [dict(method="animate", label=f"{run + pd.Timedelta(days=lead):%a %d}",
                  args=[[str(lead)], dict(mode="immediate", frame=dict(duration=0, redraw=True), transition=dict(duration=0))])
             for lead in leads]
    fig.update_layout(
        title=f"{label}, ensemble mean per LDZ — 00z run of {run:%a %d %b %Y}",
        height=820, margin=dict(l=8, r=8, t=64, b=8),
        sliders=[dict(active=0, steps=steps, x=0.08, len=0.9, y=0.02, pad=dict(t=8),
                      currentvalue=dict(prefix="Gas day ", xanchor="right", font=dict(color=t.ink, size=14)),
                      font=dict(color=t.ink_2, size=10), bgcolor=t.axis, activebgcolor=t.accent, bordercolor=t.axis,
                      tickcolor=t.muted)],
        updatemenus=[dict(type="buttons", direction="left", x=0.0, y=0.02, xanchor="left", yanchor="top", pad=dict(t=8),
                          bgcolor=t.surface, bordercolor=t.axis, font=dict(color=t.ink_2),
                          buttons=[dict(label="▶", method="animate",
                                        args=[None, dict(frame=dict(duration=700, redraw=True), fromcurrent=True,
                                                         transition=dict(duration=0))]),
                                   dict(label="❚❚", method="animate",
                                        args=[[None], dict(mode="immediate", frame=dict(duration=0, redraw=False))])])])
    return fig
