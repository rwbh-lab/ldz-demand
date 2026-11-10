import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · LDZ weather", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import pages, style
    from ldz_demand.charts import weather_ldz as wx

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return mo, pages, wx


@app.cell(hide_code=True)
def _(mo, pages):
    pages.header("ldz_weather.py", mo.md(r"""
    # LDZ weather
    *One temperature per LDZ, every gas day: how much does the way we draw and weight the LDZ matter?*
    """), mo.md(r"""
    **How the LDZ is drawn hardly matters; what is averaged over it does.** Day to day, the four LDZ maps
    give gas-weighted temperatures within a few hundredths of a degree of each other. Weighting by land
    area instead moves them by about 0.2 °C, and the official stations by about 0.4 °C, some by an amount
    that changes with the season.

    - **Weights**: which grid cells make each LDZ's weather.
    - **Spread**: how much the variants differ, day to day.
    - **One LDZ**: the daily differences, to see whether they are steady or weather-dependent.
    - **Stations**: how the official CWV stations differ through the year.
    """))
    return


@app.cell(hide_code=True)
def _(mo, wx):
    from ldz_demand.config import create_config
    from ldz_demand.data.datasets import WEATHER_LDZ_DAILY
    from ldz_demand.data.store import get_store
    from ldz_demand.geo import grid_weights

    import pandas as pd

    weights = grid_weights.load()
    # the last two full gas years and the current one: enough to show how the variants differ, at a
    # fifth of the read; only the variables this page shows (temperature, wind), 2 of the table's 7
    _today = pd.Timestamp.today()
    _since = pd.Timestamp(year=(_today.year if _today.month >= 10 else _today.year - 1) - 2, month=10, day=1)
    try:
        _long = get_store(create_config()).read(WEATHER_LDZ_DAILY, start=_since.date(), variable=list(wx.UNITS))
        load_error = None
    except Exception as exc:  # show setup help instead of a traceback
        _long, load_error = None, exc
    has_weather = _long is not None and not _long.empty
    # keep only the compact wide form (one float per gas day and series) and a few summary facts
    if has_weather:
        _t = _long[_long["variable"] == "t2m"]
        weather_facts = dict(first=_long["gas_day"].min(), last=_long["gas_day"].max(),
                             preliminary=int(_t.loc[_t["source"] == "era5t", "gas_day"].nunique()))
        weather = wx.prepare(_long)
    else:
        weather, weather_facts = None, None
    del _long
    return grid_weights, has_weather, load_error, weather, weather_facts, weights


@app.cell(hide_code=True)
def _(grid_weights, mo, pages, weights, wx):
    _variants = grid_weights.variants(weights)
    variant_options = {wx.label(v): v for v in _variants}
    ldz_options = sorted(weights["ldz"].unique())
    map_ldz = mo.ui.dropdown(options=ldz_options, value="NT", label="LDZ")
    map_variant = mo.ui.dropdown(options=list(variant_options), value=wx.label(wx.REFERENCE), label="Variant")
    mo.vstack([
        mo.md(f"""{pages.heading("Weights", "Gas-use weighting pulls each LDZ towards its towns and cities")}

    - Each LDZ's weather is a **weighted mean of ERA5 grid cells** (0.25°, about 28 × 17 km). Bigger,
      darker squares count for more.
    - **Gas use** weights each local authority by its annual gas consumption (DESNZ), spread over its
      area; **area** weights every km² of land equally, hills and moors included.
    - The official CWV uses **one station** per LDZ: compare *Station* with any other variant. EA, NT
      and SE all use Heathrow; NE uses Nottingham Watnall, which is in EM.
    """),
        mo.accordion({"More detail": mo.md(r"""
        Which cells count, and how much, is a modelling choice with two parts, and this page builds every
        combination rather than picking one:

        - **Membership:** which places belong to the LDZ. These are the four map methods from the
          [LDZ geography](/ldz-geography) page: local authority, Voronoi, hybrid and sampled.
        - **Weighting:** how the places inside the LDZ count. **Area** weights every km² of land
          equally. **Gas use** weights each local authority by its annual gas consumption (DESNZ),
          spread over its area.

        Plus the reference everything is measured against: the **official CWV's single weather station**
        per LDZ. The station's value here comes from the four ERA5 grid points around it, not from the
        station's own readings, so the comparison is like for like.
        """)}),
        mo.hstack([map_ldz, map_variant], justify="start", gap=2, wrap=True),
    ], gap=0.5)
    return ldz_options, map_ldz, map_variant, variant_options


@app.cell(hide_code=True)
def _(map_ldz, map_variant, mo, variant_options, weights, wx):
    mo.ui.plotly(wx.weights_map(weights, map_ldz.value, variant_options[map_variant.value]), config={"scrollZoom": False})
    return


@app.cell(hide_code=True)
def _(has_weather, load_error, mo):
    mo.stop(
        not has_weather,
        mo.callout(mo.md(
            "**No LDZ weather built yet.** It needs the ERA5 archive (see the [user guide, §5.2](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_guide.md#52-era5)):\n\n"
            "```bash\npython -m ldz_demand.data.ingest.era5 refresh\n"
            "python -m ldz_demand.data.build.weather_ldz_daily\n```"
            + (f"\n\nError: `{load_error}`" if load_error else "")
        ), kind="warn"),
    )
    return


@app.cell(hide_code=True)
def _(weather, wx):
    # the headline comparison, temperature against the reference: the median over LDZs of each variant's
    # day-to-day SD, grouped as the page's statements need them
    _stats = wx.comparison(weather, "t2m", wx.REFERENCE)
    _by = _stats.assign(kind=_stats["membership"].where(_stats["membership"] == "station",
                                                        _stats["weighting"].map({"gas": "map", "area": "area"})))
    headline = _by.groupby("kind")["sd_diff"].median().to_dict()  # map / area / station, °C
    headline["map_max"] = float(_by.loc[_by["kind"] == "map", "sd_diff"].max())
    return (headline,)


@app.cell(hide_code=True)
def _(headline, mo, pages, variant_options, weather_facts, wx):
    _first, _last = weather_facts["first"], weather_facts["last"]
    variable = mo.ui.dropdown(options={"Temperature": "t2m", "Wind speed": "ws10"}, value="Temperature", label="Variable")
    reference = mo.ui.dropdown(options=list(variant_options), value=wx.label(wx.REFERENCE), label="Compared with")
    metric = mo.ui.dropdown(options={"Day-to-day (SD)": "sd_diff", "Mean offset": "mean_diff", "Largest day": "max_abs_diff"},
                            value="Day-to-day (SD)", label="Measure")
    mo.vstack([
        mo.Html(pages.tiles([
            ("History", f"{(_last - _first).days / 365.25:.1f}", f"{_first:%d %b %Y} → {_last:%d %b %Y}", "years"),
            ("Variants", f"{len(variant_options)}", "4 maps × 2 weightings + station"),
            ("Preliminary days", f"{weather_facts['preliminary']}", "ERA5T, replaced by final ERA5 later"),
            ("Station vs ours", f"{headline['station']:.2f}", "day-to-day SD, median LDZ", "°C"),
        ])),
        mo.md(f"""{pages.heading("Spread", f"The official station differs most day to day: {headline['station']:.1f} °C, "
                                           f"against {headline['area']:.1f} °C for area weighting")}

    - Each dot is one variant's difference from the reference (*sampled map, gas-use weighting*) over
      every gas day, per LDZ.
    - **Day-to-day (SD)** is what matters: a constant offset, such as one variant always 0.3 °C warmer,
      is absorbed when the model is fitted; noise that changes from day to day blurs the
      temperature–demand relationship.
    - The other three maps, gas-weighted, differ by {headline['map']:.2f} °C (at most
      {headline['map_max']:.2f} °C in any LDZ): the map method hardly matters.
    - The chart starts with the **station**, **area** weighting and the **original Voronoi** map; add the
      rest with *Include*.
    """),
        mo.hstack([variable, metric, reference], justify="start", gap=2, wrap=True),
    ], gap=0.5)
    return metric, reference, variable


@app.cell(hide_code=True)
def _(mo, reference, variant_options, wx):
    _others = [v for v in variant_options if v != reference.value]
    _key = [wx.label(v) for v in (("station", "point"), ("sampled", "area"), ("voronoi", "gas"))]
    include = mo.ui.multiselect(options=_others, value=[v for v in _key if v in _others], label="Include")
    include
    return (include,)


@app.cell(hide_code=True)
def _(include, metric, mo, reference, variable, variant_options, weather, wx):
    _ref = variant_options[reference.value]
    stats = wx.comparison(weather, variable.value, _ref)
    stats = stats[stats["variant"].isin(include.value)]
    mo.stop(stats.empty, mo.callout(mo.md("Choose at least one variant to include."), kind="info"))
    _table = (stats.pivot_table(index="ldz", columns="variant", values=metric.value).round(2)
              .reset_index().rename(columns={"ldz": "LDZ"}))
    _name = dict(sd_diff="SD of the daily difference", mean_diff="Mean offset", max_abs_diff="Largest daily difference")[metric.value]
    mo.vstack([
        mo.ui.plotly(wx.spread_chart(stats, variable.value, metric.value, _ref)),
        mo.accordion({f"{_name} from {reference.value}, by LDZ ({wx.UNITS[variable.value]}, table)":
                      mo.ui.table(_table, selection=None, pagination=False, show_column_summaries=False,
                                  show_data_types=False, show_search=False)}),
    ])
    return


@app.cell(hide_code=True)
def _(ldz_options, mo, pages, variant_options, wx):
    detail_ldz = mo.ui.dropdown(options=ldz_options, value="NT", label="LDZ")
    _default = [wx.label(v) for v in (("station", "point"), ("authority", "gas"), ("voronoi", "gas"), ("hybrid", "gas"),
                                     ("sampled", "area"))]
    detail_variants = mo.ui.multiselect(options=list(variant_options), value=[v for v in _default if v in variant_options],
                                        label="Variants")
    show_values = mo.ui.switch(value=False, label="Show the values, not the differences")
    mo.vstack([
        mo.md(f"""{pages.heading("One LDZ", "Steady differences are absorbed; weather-dependent ones blur the fit")}

    - The daily difference from the reference above, for one LDZ.
    - Look for whether a difference is **steady**, which the model absorbs, or **weather-dependent**:
      larger on cold still nights, or on days when the coast and inland differ.
    - Drag the slider under the chart to zoom into a winter.
    """),
        mo.hstack([detail_ldz, detail_variants], justify="start", gap=2, wrap=True),
        show_values,
    ], gap=0.5)
    return detail_ldz, detail_variants, show_values


@app.cell(hide_code=True)
def _(detail_ldz, detail_variants, mo, reference, show_values, variable, variant_options, weather, wx):
    _variants = [variant_options[v] for v in detail_variants.value]
    _ref = variant_options[reference.value]
    mo.ui.plotly(
        wx.series_chart(weather, detail_ldz.value, [_ref] + _variants, variable.value) if show_values.value
        else wx.difference_chart(weather, detail_ldz.value, _variants, variable.value, _ref))
    return


@app.cell(hide_code=True)
def _(mo, pages, weather, wx):
    import calendar

    from ldz_demand.geo.ldz_membership import read_table

    _offsets = wx.station_offsets(weather, "t2m")
    # the seasonal part is what a fit can't absorb: each station's swing in its monthly mean gap
    _by = _offsets.groupby("ldz")["mean"]
    _swing = (_by.max() - _by.min()).sort_values(ascending=False)
    _ldz = _swing.index[0]
    _stations = read_table("cwv_stations.csv")
    _names = _stations[_stations["variable"].isin(["all", "t2m"])].set_index("ldz")["station"]
    _peak = _offsets.loc[_by.idxmax()].set_index("ldz")
    mo.vstack([
        mo.md(f"""{pages.heading("Stations", f"The station gaps change through the year by up to {_swing.iloc[0]:.1f} °C "
                                             f"({_names.get(_ldz, 'its station')}, {_ldz})")}

    - How much warmer (red) or colder (blue) the official station reads than our gas-weighted LDZ
      temperature, on average in each month.
    - A **constant** gap is absorbed when the model is fitted; one that **changes through the year** is
      not, unless the model has a seasonal term to soak it up.
    - The coastal stations swing with the sea, warmer than the inland towns in autumn and winter:
      St Athan (WS) by up to {_peak.loc['WS', 'mean']:.1f} °C, in {calendar.month_name[int(_peak.loc['WS', 'month'])]}.
    """),
        mo.accordion({"More detail": mo.md(r"""
        **St Athan (WS)** reads warm in autumn and winter, when the sea is warmer than the inland towns
        and valleys where WS's gas is used, and almost nothing in late spring; **Southampton (SO)** the
        same, weaker; **Heathrow** reads colder than SE's coastal towns in autumn. **Nottingham Watnall**
        stands in for NE from EM and reads warm all year, most in summer. The official CWV's seasonal
        profile (pseudo-SNET) may be partly correcting for where its stations are, which our
        gas-weighted temperature shouldn't need. ERA5, every gas day of the history above.
        """)}),
        mo.ui.plotly(wx.station_offset_chart(_offsets, "t2m")),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.accordion({
        "How this was built": mo.md(r"""
        - Cell weights: `python -m ldz_demand.geo build` → `ldz_demand/geo/data/ldz_cell_weights.csv`
          (code: `ldz_demand.geo.grid_weights`). Station locations and sources: `cwv_stations.csv`.
        - LDZ weather: `python -m ldz_demand.data.build.weather_ldz_daily` → table `weather_ldz_daily`
          (code: `ldz_demand.data.build.weather_ldz_daily`). Gas days run 05:00–05:00 UK time; wind speed is
          computed hourly from its components before the daily mean.
        - Within a split authority, the local-authority and sampled methods spread the authority's shares
          evenly over its area; Voronoi and hybrid cut it along their LDZ boundaries.
        """),
        "Sources & attribution": mo.md(
            "Weather: Copernicus Climate Change Service, ERA5 hourly data on single levels (contains modified "
            "Copernicus Climate Change Service information). Weather stations per LDZ: National Gas, *Gas Demand "
            "Forecasting Methodology* (2016), Table A1.1; station coordinates approximate. Boundaries: ONS Local "
            "Authority Districts, December 2023 (contains OS data © Crown copyright and database right 2023). Gas use: "
            "DESNZ subnational gas consumption statistics, 2024. ONS/DESNZ data under the Open Government Licence v3.0."),
    })
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer()
    return


if __name__ == "__main__":
    app.run()
