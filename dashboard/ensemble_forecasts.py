import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Ensemble LDZ weather", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import ensemble as ens
    from ldz_demand.charts import style

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return ens, mo


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.charts import pages as _pages

    _pages.header("ensemble_forecasts.py", mo.md(r"""
    # Ensemble LDZ weather
    *Fifty equally likely futures for each LDZ, every day, out to 15 days.*
    """), mo.md(r"""
    The official forecast gives one Composite Weather Variable per LDZ and gas day. The ECMWF
    ensemble gives **50 members**, each an equally likely version of the next 15 days, run through our
    LDZ map and gas-use weighting. The spread between them is the forecast's uncertainty, and its
    **shape** matters as much as its size: demand rises faster as it gets colder, so a long cold tail
    lifts expected demand above "demand at the average forecast temperature". This page looks at that
    shape before it goes into the demand model.

    Data: the 00z run each day (published ~09:30 UTC), per LDZ, gas days 0 (the run's own day) to 14.
    """))
    return


@app.cell(hide_code=True)
def _(ens, mo):
    from datetime import timedelta

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
    # the runs available: a light read (one LDZ, one variable) over the last few weeks
    _probe = store.read(ENS_LDZ_DAILY, start=_last - timedelta(days=30), end=_last, ldz="NT", variable="t2m",
                        membership="station", member=1, lead_days=0)
    runs = sorted(_probe["run_date"].dt.date.unique(), reverse=True)
    return ENS_LDZ_DAILY, runs, store


@app.cell(hide_code=True)
def _(ENS_LDZ_DAILY, ens, mo, runs, store):
    # the latest run only: one variable, our gas-weighted LDZ weather (a light read)
    _latest = runs[0]
    _rows = store.read(ENS_LDZ_DAILY, start=_latest, end=_latest, variable="t2m", membership=ens.REFERENCE[0])
    mo.vstack([
        mo.md(r"""
        ## The next two weeks at a glance

        The latest run's **ensemble mean** temperature for each LDZ — the average of the 50 members, on our
        LDZ map and weighted by where gas is used. Drag the slider, or press ▶, to step through the 14 gas
        days; hover an LDZ for the spread (P10–P90). Blue is colder than about 15.5 °C, roughly where
        heating comes on. The sections below take one run and one LDZ at a time, in more detail.
        """),
        ens.mean_map(ens.cube(_rows), _latest),
    ])
    return


@app.cell(hide_code=True)
def _(ens, mo, runs):
    run_picker = mo.ui.dropdown(options={f"{r:%a %d %b %Y}": r for r in runs}, value=f"{runs[0]:%a %d %b %Y}",
                                label="Run (00z)")
    ldz_picker = mo.ui.dropdown(options=[ens.GB, *ens.LDZS], value=ens.GB, label="LDZ")
    mo.hstack([run_picker, ldz_picker], justify="start", gap=2)
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
    mo.vstack([
        mo.md(r"""
        ## 1 · The forecast fan

        The shaded bands hold the middle 80% (P10–P90) and middle 50% (P25–P75) of the members, around
        the median; the dotted line is the mean. Where the median sits off-centre in its band, or the
        mean pulls away from the median, the members are lopsided. *GB* is the LDZs weighted by their
        share of gas use. The station comparison shows the same forecast taken at the official CWV
        weather station instead of our gas-weighted LDZ average.
        """),
        mo.hstack([variable_picker, members_switch, station_switch], justify="start", gap=2),
    ])
    return members_switch, station_switch, variable_picker


@app.cell(hide_code=True)
def _(cube, ens, ldz_picker, members_switch, mo, run_date, station_switch, variable_picker):
    _ldz, _variable = ldz_picker.value, variable_picker.value
    _compare = ("station", "point") if station_switch.value and _ldz != ens.GB else None
    _note = mo.md("")
    if station_switch.value and _ldz == ens.GB:
        _note = mo.md("*The station comparison is per LDZ — there is no single GB station.*")
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
def _(cube, mo):
    lead_picker = mo.ui.slider(start=0, stop=int(cube["lead"].max()), value=9, step=1, label="Lead day", show_value=True)
    scale_picker = mo.ui.dropdown(options={"In standard deviations (growth removed)": "sd", "In the variable's units": "units"},
                                  value="In standard deviations (growth removed)", label="Scale")
    mo.vstack([
        mo.md(r"""
        ## 2 · Is the spread lopsided?

        For each lead day, the two sides of the spread: down to P10 (left) and up to P90 (right). Equal
        bars mean a balanced spread; a longer left bar means a longer **cold** tail — for demand, the side
        that matters, because demand rises faster as it gets colder. **In standard deviations** (the
        default), each side is measured from the mean and divided by that day's spread, so the growth in
        uncertainty with lead time is taken out: a symmetric bell-shaped spread sits on the dashed lines
        (1.28 either side), and anything else is lopsidedness. **In the variable's units** shows the raw
        distances from the median, spread growth included. Hover for Kelly's skewness (−1 to 1). Below,
        every member on one lead day.
        """),
        mo.hstack([scale_picker, lead_picker], justify="start", gap=2),
    ])
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
def _(mo):
    measure_picker = mo.ui.dropdown(options={"Spread (P25–P75)": "iqr", "Lopsidedness (Kelly skewness)": "kelly"},
                                    value="Spread (P25–P75)", label="Colour by")
    mo.vstack([
        mo.md(r"""
        ## 3 · Where the uncertainty is

        Every LDZ and lead day for the selected run and variable: how wide the middle half of the
        members is, or which way it leans.
        """),
        measure_picker,
    ])
    return (measure_picker,)


@app.cell(hide_code=True)
def _(cube, ens, measure_picker, mo, run_date, variable_picker):
    mo.ui.plotly(ens.spread_heatmap(cube, run_date, variable_picker.value, measure_picker.value))
    return


@app.cell(hide_code=True)
def _(mo, runs):
    mo.md(rf"""
    ## 4 · Run to run — 🚧 as the archive grows

    How the forecast for one gas day changes from run to run as the day gets closer: the spread should
    narrow, and a lopsided tail may grow or vanish. {len(runs)} run(s) archived so far; this needs a week
    or two of runs to say much.

    ## 5 · Did it happen? — 🚧 once ERA5 catches up

    ERA5 runs ~5 days behind, so the first forecasts can soon be checked against what happened: does the
    actual temperature fall inside the P10–P90 band about 80% of the time, does the spread match the
    errors, and is the lopsidedness real information or noise? That decides how far the demand model
    should trust the shape of the spread.
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
            "Forecasts: ECMWF open data, IFS ensemble (CC-BY-4.0) — contains ECMWF open data. LDZ map and "
            "weights: see the LDZ geography page."),
    })
    return


if __name__ == "__main__":
    app.run()
