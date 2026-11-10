import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Ensemble LDZ weather", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import ensemble as ens
    from ldz_demand.charts import pages, style

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    P10, P25, P50, P75, P90 = (pages.P(q) for q in (10, 25, 50, 75, 90))
    return P10, P25, P50, P75, P90, ens, mo, pages


@app.cell(hide_code=True)
def _(P10, P90, mo, pages):
    pages.header("ensemble_forecasts.py", mo.md(r"""
    # Ensemble LDZ weather
    *Fifty equally likely futures for each LDZ, every day, out to 15 days.*
    """), mo.md(rf"""
    **The official forecast gives one weather value per LDZ and day; the ECMWF ensemble gives 50 equally
    likely ones.** Their spread is the forecast's uncertainty: a fraction of a degree for the next few
    days, several degrees by the second week. Its shape matters as much as its size, because demand
    rises faster as it gets colder.

    - **Two weeks**: the latest run's mean temperature per LDZ, day by day.
    - **Fan**: one LDZ's forecast, with its {P10}–{P90} range.
    - **Lopsided**: whether the cold or the warm tail is longer.
    - **Where**: the spread for every LDZ and lead day.

    Data: the 00z run each day (published ~09:30 UTC), per LDZ, on our LDZ map and gas-use weighting,
    gas days 0 (the run's own day) to 14.
    """))
    return


@app.cell(hide_code=True)
def _(ens, mo):
    from datetime import timedelta

    import pandas as pd

    from ldz_demand.config import create_config
    from ldz_demand.data.datasets import ENS_LDZ_DAILY
    from ldz_demand.data.store import get_store

    try:
        store = get_store(create_config())
        _last = store.last_date(ENS_LDZ_DAILY)
        load_error = None
    except Exception as exc:  # show setup help instead of a traceback
        store, _last, load_error = None, None, exc
    mo.stop(
        _last is None,
        mo.callout(mo.md(
            "**No ensemble forecasts built yet.** They come from the archived runs (see the [user guide, §5.3](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_guide.md#53-ecmwf-ensemble)):\n\n"
            "```bash\npython -m ldz_demand.data.ingest.ecmwf_ens refresh\npython -m ldz_demand.data.build.ens_ldz_daily\n```"
            + (f"\n\nError: `{load_error}`" if load_error else "")), kind="warn"),
    )
    # the runs available over the last few weeks: one row per run. The dates go in as a list, so the read
    # follows the table's key (run_date, run_hour, member, ...); a date range would scan every row of every run.
    _days = [pd.Timestamp(_last - timedelta(days=i)) for i in range(31)]  # Timestamps match in both stores
    _probe = store.read(ENS_LDZ_DAILY, run_date=_days, run_hour=0, member=1, ldz="NT", variable="t2m",
                        membership="station", lead_days=0)
    runs = sorted(_probe["run_date"].dt.date.unique(), reverse=True)
    return ENS_LDZ_DAILY, runs, store


@app.cell(hide_code=True)
def _(ENS_LDZ_DAILY, P10, P90, ens, mo, pages, runs, store):
    from datetime import timedelta as _td

    # the latest run only: one variable, our gas-weighted LDZ weather (a light read)
    _latest = runs[0]
    _rows = store.read(ENS_LDZ_DAILY, start=_latest, end=_latest, variable="t2m", membership=ens.REFERENCE[0])
    _cube = ens.cube(_rows)
    _gb = ens.with_gb(_cube, ens.gas_shares()).sel(variant="/".join(ens.REFERENCE), variable="t2m", ldz=ens.GB)
    _mean = _gb.mean("member").to_series()
    _cold = int(_mean.idxmin())
    mo.vstack([
        mo.Html(pages.tiles([
            ("Latest run", f"{_latest:%a %d %b}", "00z, published ~09:30 UTC"),
            ("Members", f"{_gb.sizes['member']}", "equally likely"),
            ("Gas days", f"{_gb.sizes['lead']}", "day 0 to day 14"),
            ("Runs", f"{len(runs)}", "in the last 31 days"),
        ])),
        mo.md(f"""{pages.heading("Two weeks", f"The coldest gas day ahead for GB is {_latest + _td(days=_cold):%a %d %b}, "
                                              f"at {_mean.iloc[_cold]:.1f} °C")}

    - The latest run's **ensemble mean** temperature for each LDZ: the average of the 50 members.
    - Blue is colder than about 15.5 °C, roughly where heating comes on.
    - Drag the slider, or press ▶, to step through the days; hover an LDZ for its {P10}–{P90} range.
    """),
        ens.mean_map(_cube, _latest),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(ens, mo, runs):
    run_picker = mo.ui.dropdown(options={f"{r:%a %d %b %Y}": r for r in runs}, value=f"{runs[0]:%a %d %b %Y}",
                                label="Run (00z)")
    ldz_picker = mo.ui.dropdown(options=[ens.GB, *ens.LDZS], value=ens.GB, label="LDZ")
    mo.vstack([
        mo.md("*The sections below take one run and one LDZ at a time.*"),
        mo.hstack([run_picker, ldz_picker], justify="start", gap=2, wrap=True),
    ], gap=0.5)
    return ldz_picker, run_picker


@app.cell(hide_code=True)
def _(ENS_LDZ_DAILY, ens, run_picker, store):
    _rows = store.read(ENS_LDZ_DAILY, start=run_picker.value, end=run_picker.value)
    cube = ens.with_gb(ens.cube(_rows), ens.gas_shares())
    run_date = run_picker.value
    variables = [v for v in ens.VARIABLES if v in cube["variable"].values]
    return cube, run_date, variables


@app.cell(hide_code=True)
def _(ens, mo, variables):
    variable_picker = mo.ui.dropdown(options={ens.VARIABLES[v][0]: v for v in variables},
                                     value=ens.VARIABLES["t2m"][0], label="Variable")
    members_switch = mo.ui.switch(value=False, label="Show the 50 members")
    station_switch = mo.ui.switch(value=False, label="Compare with the official station")
    return members_switch, station_switch, variable_picker


@app.cell(hide_code=True)
def _(P10, P25, P50, P75, P90, cube, ens, ldz_picker, members_switch, mo, pages, station_switch, variable_picker):
    # the selected LDZ and variable's spread, for the headings here and in the next section
    spread = ens.asymmetry(cube.sel(variant="/".join(ens.REFERENCE), variable=variable_picker.value,
                                    ldz=ldz_picker.value))
    _unit = ens.VARIABLES[variable_picker.value][1]
    _width = spread["lower"] + spread["upper"]
    _widest = int(_width.idxmax())
    mo.vstack([
        mo.md(f"""{pages.heading("Fan", f"{ldz_picker.value}'s {P10}–{P90} range grows from {_width.iloc[0]:.1f} {_unit} "
                                       f"on day 0 to {_width.iloc[_widest]:.1f} {_unit} by day {_widest}")}

    - The shaded bands hold the middle 80% ({P10}–{P90}) and middle 50% ({P25}–{P75}) of the members,
      around the median ({P50}); the dotted line is the mean.
    - Where the median sits off-centre in its band, or the mean pulls away from it, the members are
      lopsided (next section).
    - *GB* is the LDZs weighted by their share of gas use. The station comparison takes the same
      forecast at the official CWV station instead of our gas-weighted average.
    """),
        mo.hstack([variable_picker, members_switch, station_switch], justify="start", gap=2, wrap=True),
    ], gap=0.5)
    return (spread,)


@app.cell(hide_code=True)
def _(cube, ens, ldz_picker, members_switch, mo, run_date, station_switch, variable_picker):
    _ldz, _variable = ldz_picker.value, variable_picker.value
    _compare = ("station", "point") if station_switch.value and _ldz != ens.GB else None
    _note = mo.md("")
    if station_switch.value and _ldz == ens.GB:
        _note = mo.md("*The station comparison is per LDZ: there is no single GB station.*")
    elif _compare is not None:
        # the usual station gap for this LDZ and month (ERA5; every LDZ read once, then kept)
        _note = mo.callout(mo.md(ens.station_gap_note(ens.station_gap(cube, _ldz, _variable),
                                                      ens.usual_station_gaps(_variable),
                                                      run_date, _ldz, _variable)), kind="neutral")
    mo.vstack([
        mo.ui.plotly(ens.fan_chart(cube, run_date, _ldz, _variable, compare=_compare, show_members=members_switch.value)),
        _note,
    ])
    return


@app.cell(hide_code=True)
def _(P10, P90, cube, ens, ldz_picker, mo, pages, spread, variable_picker):
    lead_picker = mo.ui.slider(start=0, stop=int(cube["lead"].max()), value=9, step=1, label="Lead day", show_value=True)
    scale_picker = mo.ui.dropdown(options={"In standard deviations (growth removed)": "sd", "In the variable's units": "units"},
                                  value="In standard deviations (growth removed)", label="Scale")
    _low, _high = ens.VARIABLES[variable_picker.value][2]
    _lead = int(spread["kelly"].abs().idxmax())
    _k = float(spread["kelly"].loc[_lead])
    _statement = (f"{ldz_picker.value} is balanced in this run: no lead day leans far either way"
                  if abs(_k) < 0.25 else
                  f"{ldz_picker.value} leans {_low if _k < 0 else _high} at day {_lead} (Kelly skewness {_k:+.2f})".replace("-", "−"))
    mo.vstack([
        mo.md(f"""{pages.heading("Lopsided", _statement)}

    - For each lead day, the two sides of the spread: down to {P10} (left) and up to {P90} (right).
    - A longer left bar is a longer **cold** tail: the side that matters for demand, which rises faster
      as it gets colder.
    - Below, every member on one lead day.
    """),
        mo.accordion({"More detail": mo.md(r"""
        **In standard deviations** (the default), each side is measured from the mean and divided by that
        day's spread, so the growth in uncertainty with lead time is taken out: a symmetric bell-shaped
        spread sits on the dashed lines (1.28 either side), and anything else is lopsidedness. **In the
        variable's units** shows the raw distances from the median, spread growth included. Hover for
        Kelly's skewness, from −1 (all the spread on the low side) to 1; the heading calls ±0.25 or more
        a lean.
        """)}),
        mo.hstack([scale_picker, lead_picker], justify="start", gap=2, wrap=True),
    ], gap=0.5)
    return lead_picker, scale_picker


@app.cell(hide_code=True)
def _(cube, ens, lead_picker, ldz_picker, mo, run_date, scale_picker, variable_picker):
    mo.vstack([
        mo.ui.plotly(ens.asymmetry_chart(cube, run_date, ldz_picker.value, variable_picker.value,
                                         scale=scale_picker.value)),
        mo.ui.plotly(ens.members_strip(cube, run_date, ldz_picker.value, variable_picker.value, lead_picker.value)),
    ])
    return


@app.cell(hide_code=True)
def _(P25, P75, mo, pages):
    measure_picker = mo.ui.dropdown(options={"Spread (P25–P75)": "iqr", "Lopsidedness (Kelly skewness)": "kelly"},
                                    value="Spread (P25–P75)", label="Colour by")
    mo.vstack([
        mo.md(f"""{pages.heading("Where", "Uncertainty grows with lead day, and not evenly across LDZs")}

    - Every LDZ and lead day for the selected run and variable: how wide the middle half of the members
      is ({P25}–{P75}), or which way it leans.
    """),
        measure_picker,
    ], gap=0.5)
    return (measure_picker,)


@app.cell(hide_code=True)
def _(cube, ens, measure_picker, mo, run_date, variable_picker):
    mo.ui.plotly(ens.spread_heatmap(cube, run_date, variable_picker.value, measure_picker.value))
    return


@app.cell(hide_code=True)
def _(P10, P90, mo, pages):
    mo.md(f"""{pages.heading("Still to come", "Run-to-run changes, and checks against what happened")}

    - **Run to run**: how the forecast for one gas day changes as the day gets closer. The spread should
      narrow, and a lopsided tail may grow or vanish.
    - **Did it happen?** ERA5 runs six days behind, so past forecasts can be checked: does the actual
      temperature fall inside {P10}–{P90} about 8 times in 10, and is the lopsidedness information or
      noise? That decides how far the demand model should trust the shape of the spread.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.accordion({
        "How this was built": mo.md(r"""
        - Runs: `python -m ldz_demand.data.ingest.ecmwf_ens refresh` (the daily scheduled job) → LDZ values:
          `python -m ldz_demand.data.build.ens_ldz_daily` → table `ens_ldz_daily`.
        - Each member's gas-day values use the same cell weights as the ERA5 tables (LDZ geography and
          LDZ weather pages); temperature and wind are averaged over the gas day, the extremes, solar
          radiation and precipitation come from each forecast step's period.
        - Runs archived before 13 October 2026 have temperature and wind only.
        - Code: `ldz_demand.charts.ensemble`.
        """),
        "Sources & attribution": mo.md(
            "Forecasts: ECMWF open data, IFS ensemble (CC-BY-4.0); contains ECMWF open data. LDZ map and "
            "weights: see the LDZ geography page."),
    })
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer()
    return


if __name__ == "__main__":
    app.run()
