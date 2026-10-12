import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · LDZ weather", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import style
    from ldz_demand.charts import weather_ldz as wx

    theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return mo, wx


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # LDZ weather
    *One temperature per LDZ, every gas day: how much does the way we draw and weight the LDZ matter?*

    The demand model takes each LDZ's weather as a **weighted mean of ERA5 grid cells** (0.25°,
    roughly 28 × 17 km). Which cells count, and how much, is a modelling choice with two parts, and
    this page builds every combination rather than picking one:

    - **Membership:** which places belong to the LDZ. These are the four map methods from the
      *LDZ geography* page: local authority, Voronoi, hybrid and sampled.
    - **Weighting:** how the places inside the LDZ count. **Area** weights every km² of land
      equally. **Gas use** weights each local authority by its annual gas consumption (DESNZ),
      spread over its area.

    Plus the reference everything is measured against: the **official CWV's single weather
    station** per LDZ. EA, NT and SE all use Heathrow, and NE uses Nottingham Watnall, which is in
    EM. The station's value comes from the four ERA5 grid points around it, not from the station's
    own readings.

    **What matters for the model** is the *day-to-day* difference between variants. A constant offset,
    such as one variant always 0.3 °C warmer, is absorbed when the model is fitted. Noise that changes
    from day to day is not: it blurs the temperature–demand relationship.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.config import create_config
    from ldz_demand.data.datasets import WEATHER_LDZ_DAILY
    from ldz_demand.data.store import get_store
    from ldz_demand.geo import grid_weights

    weights = grid_weights.load()
    try:
        weather = get_store(create_config()).read(WEATHER_LDZ_DAILY)
        load_error = None
    except Exception as exc:  # show setup help instead of a traceback
        weather, load_error = None, exc
    has_weather = weather is not None and not weather.empty
    return grid_weights, has_weather, load_error, weather, weights


@app.cell(hide_code=True)
def _(grid_weights, mo, weights, wx):
    _variants = grid_weights.variants(weights)
    variant_options = {wx.label(v): v for v in _variants}
    ldz_options = sorted(weights["ldz"].unique())
    map_ldz = mo.ui.dropdown(options=ldz_options, value="NT", label="LDZ")
    map_variant = mo.ui.dropdown(options=list(variant_options), value=wx.label(wx.REFERENCE), label="Variant")
    mo.vstack([
        mo.md(r"""
        ## 1 · Where each LDZ's weather comes from

        The cell weights behind each variant. Bigger, darker squares count for more. Gas-use weighting
        pulls each LDZ towards its towns and cities; area weighting spreads it over hills and moors.
        Compare *Station* with any other variant to see how little of an LDZ one station represents.
        """),
        mo.hstack([map_ldz, map_variant], justify="start", gap=2),
    ])
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
            "**No LDZ weather built yet.** It needs the ERA5 archive (see `docs/user_guide.md` §5.2):\n\n"
            "```bash\npython -m ldz_demand.data.ingest.era5 refresh\n"
            "python -m ldz_demand.data.build.weather_ldz_daily\n```"
            + (f"\n\nError: `{load_error}`" if load_error else "")
        ), kind="warn"),
    )
    return


@app.cell(hide_code=True)
def _(mo, variant_options, weather, wx):
    _days = weather["gas_day"]
    _prelim = int((weather.loc[weather["variable"] == "t2m", "source"] == "era5t").sum() /
                  max(1, weather.loc[weather["variable"] == "t2m"].groupby(["ldz", "membership", "weighting"]).ngroups))
    variable = mo.ui.radio(options={"Temperature": "t2m", "Wind speed": "ws10"}, value="Temperature",
                           label="Variable", inline=True)
    reference = mo.ui.dropdown(options=list(variant_options), value=wx.label(wx.REFERENCE), label="Compared with")
    metric = mo.ui.radio(options={"Day-to-day (SD)": "sd_diff", "Mean offset": "mean_diff", "Largest day": "max_abs_diff"},
                         value="Day-to-day (SD)", label="Measure", inline=True)
    mo.vstack([
        mo.md(r"""
        ## 2 · How much do the variants differ?

        Each dot is one variant's difference from the chosen reference over every gas day. The default
        reference is *sampled membership, gas-use weighting*, the best-checked map with the most
        physical weighting. **Day-to-day (SD)** is the measure that matters for the model; mean
        offsets are shown for completeness. LDZs with the largest differences are at the top.
        """),
        mo.hstack([
            mo.stat(f"{(_days.max() - _days.min()).days / 365.25:.1f} years", label="History",
                    caption=f"{_days.min():%d %b %Y} → {_days.max():%d %b %Y}"),
            mo.stat(f"{len(variant_options)}", label="Variants", caption="4 maps × 2 weightings + station"),
            mo.stat(f"{_prelim}", label="Preliminary days", caption="ERA5T, replaced by final ERA5 later"),
        ], widths="equal", gap=1),
        mo.hstack([variable, metric], justify="start", gap=2),
        reference,
    ])
    return metric, reference, variable


@app.cell(hide_code=True)
def _(metric, mo, reference, variable, variant_options, weather, wx):
    _ref = variant_options[reference.value]
    stats = wx.comparison(weather, variable.value, _ref)
    _table = (stats.pivot_table(index="ldz", columns="variant", values=metric.value).round(2)
              .reset_index().rename(columns={"ldz": "LDZ"}))
    mo.vstack([
        mo.ui.plotly(wx.spread_chart(stats, variable.value, metric.value, _ref)),
        mo.md(f"**{dict(sd_diff='SD of the daily difference', mean_diff='Mean offset', max_abs_diff='Largest daily difference')[metric.value]}"
              f" from {reference.value}** ({wx.UNITS[variable.value]})"),
        mo.ui.table(_table, selection=None, pagination=False, show_column_summaries=False, show_data_types=False,
                    show_search=False),
    ])
    return


@app.cell(hide_code=True)
def _(ldz_options, mo, variant_options, wx):
    detail_ldz = mo.ui.dropdown(options=ldz_options, value="NT", label="LDZ")
    _default = [wx.label(v) for v in (("station", "point"), ("authority", "gas"), ("voronoi", "gas"), ("hybrid", "gas"),
                                     ("sampled", "area"))]
    detail_variants = mo.ui.multiselect(options=list(variant_options), value=[v for v in _default if v in variant_options],
                                        label="Variants")
    show_values = mo.ui.switch(value=False, label="Show the values, not the differences")
    mo.vstack([
        mo.md(r"""
        ## 3 · One LDZ, day by day

        The daily difference from the reference above. Look for whether the differences are
        **steady**, which the model absorbs, or **weather-dependent**, for example larger on cold
        still nights or on days when the coast and inland differ. Drag the slider under the chart
        to zoom into a winter.
        """),
        mo.hstack([detail_ldz, detail_variants], justify="start", gap=2),
        show_values,
    ])
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


if __name__ == "__main__":
    app.run()
