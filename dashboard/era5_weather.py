import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · ERA5 weather", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import era5 as ch
    from ldz_demand.charts import style

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return ch, mo


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.charts import pages as _pages

    _pages.header("era5_weather.py", mo.md(r"""
    # ERA5 weather
    *The hourly weather the model is trained on: temperature and wind on a 0.25° grid over Great Britain.*
    """), mo.md(r"""
    **ERA5** is ECMWF's reanalysis: a reconstruction of the weather every hour since 1940, made by
    combining observations with a weather model. It is what the demand model is trained on — the same
    kind of 2 m temperature and 10 m wind fields that the ECMWF ensemble will forecast later.

    The raw grid is 0.25° (~28 km). Below, it is averaged into coarser square cells so each can be labelled,
    and you can step through the **gas day** — 05:00 to 05:00 UK time, the day gas demand is measured
    over. Pick one of a few days chosen from the archive for what they show.
    """))
    return


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.config import create_config, resolve_path
    from ldz_demand.data.ingest.era5 import month_files

    raw_dir = resolve_path(create_config(), "storage", "raw_dir")
    available = month_files(raw_dir)
    mo.stop(
        not available,
        mo.callout(mo.md(
            f"**No ERA5 files found** under `{raw_dir}/era5`. Download them first — see "
            "[user guide, §5.2](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_guide.md#52-era5):\n\n```bash\npython -m ldz_demand.data.ingest.era5 refresh\n```"
        ), kind="warn"),
    )
    return available, raw_dir


@app.cell(hide_code=True)
def _(available, ch, mo):
    _days = [d for d in ch.SAMPLE_DAYS if d.day[:7] in available]
    day_picker = mo.ui.dropdown(options={d.label: d.day for d in _days}, value=_days[0].label, label="Gas day")
    variable_picker = mo.ui.dropdown(options={v["label"]: k for k, v in ch.VARIABLES.items()},
                                     value="Temperature", label="Show")
    step_picker = mo.ui.dropdown(options=ch.CELL_SIZES, value="~110 km cells", label="Grid")
    mo.hstack([day_picker, variable_picker, step_picker], justify="start", gap=2)
    return day_picker, step_picker, variable_picker


@app.cell(hide_code=True)
def _(ch, day_picker, raw_dir):
    hourly = ch.load_gas_day(raw_dir, day_picker.value)
    sample = next(d for d in ch.SAMPLE_DAYS if d.day == day_picker.value)
    return hourly, sample


@app.cell(hide_code=True)
def _(ch, hourly, mo, sample):
    _s = ch.day_summary(hourly)
    mo.vstack([
        mo.md(f"**{sample.label}.** {sample.why}"),
        mo.hstack([
            mo.stat(f"{_s['t_mean']:.1f} °C", label="England mean temperature",
                    caption=f"hourly range {_s['t_min']:.1f} → {_s['t_max']:.1f} °C"),
            mo.stat(f"{_s['ws_mean']:.1f} m/s", label="Mean wind, GB box", caption=f"strongest cell-hour {_s['ws_max']:.0f} m/s"),
            mo.stat(f"{_s['hours']} h", label="Gas day", caption="05:00 → 05:00 UK time"),
        ], widths="equal", gap=1),
    ])
    return


@app.cell(hide_code=True)
def _(ch, hourly, mo, step_picker, variable_picker):
    # scroll-zoom off so scrolling the page doesn't zoom the map; zoom with the +/- buttons instead
    mo.ui.plotly(ch.grid_map(hourly, variable_picker.value, step_picker.value), config={"scrollZoom": False})
    return


@app.cell(hide_code=True)
def _(ch, mo):
    mo.accordion({
        "Reading the map": mo.md(rf"""
        - Drag the slider or press ▶ to step through the gas day. Hover a cell for its exact value.
        - **Temperature** is coloured around **{ch.HEATING_THRESHOLD} °C**, roughly where space heating
          switches on: blue cells need heating, and the deeper the blue the more. The scale is fixed
          (−9.5 → 40.5 °C), so days and hours compare directly.
        - **Wind** is 10 m wind speed on a fixed 0–20 m/s scale, dark purple (calm) through red and
          orange to yellow (storm). Wind makes buildings lose heat faster, which is why the official CWV
          includes it.
        - Cells cover sea as well as land; the offshore cells are milder in winter and cooler in summer.
        """),
        "How this was computed": mo.md(r"""
        - ERA5 hourly 2 m temperature and 10 m wind (u, v) over 61°N 8.5°W – 49.5°N 2°E; wind speed = √(u² + v²).
        - Hours assigned to the UK gas day on the local wall clock (05:00 → 05:00, 23 or 25 hours across clock changes).
        - Cells: the 0.25° grid, cropped to mainland GB (49.75–59.5°N), averaged in blocks of 4 × 7 (~110 km)
          or 2 × 3 (~55 km) grid points — wider in longitude so cells are square on the ground. Partial
          blocks at the edge are dropped.
        - Headline temperature: mean over an England box (50.5–54°N, 3°W–0.5°E).
        - Code: `ldz_demand.charts.era5` · data: [user guide, §4.2](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_guide.md#42-era5--hourly-reanalysis-weather).
        """),
        "Attribution": mo.md("Contains modified Copernicus Climate Change Service information [2021–2026]. "
                             "Neither the European Commission nor ECMWF is responsible for any use of this information. "
                             "Coastline: Natural Earth (public domain)."),
    })
    return


if __name__ == "__main__":
    app.run()
