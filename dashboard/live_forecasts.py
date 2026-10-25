import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Live forecasts", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import forecasts as fch
    from ldz_demand.charts import style
    from ldz_demand.models import forecast as fcm

    theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return fch, fcm, mo


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.charts import pages as _pages

    _pages.header("live_forecasts.py", mo.md(r"""
    # Live forecasts
    *Gas demand for the next two weeks, per LDZ, from the ECMWF ensemble.*
    """), mo.md(r"""
    Each day's 00z ensemble gives 50 equally likely versions of the next 15 days' weather. Each goes
    through the [demand model](/model-specification), giving 50 demand paths per LDZ for lead days 0–13; GB is
    their sum, member by member.

    **The intervals include the model's own error, not just the weather's.** On its own, the spread of
    the 50 members is far too narrow at short leads: it says how uncertain the weather is, not how far
    the model can be off when the weather is known. So each member is combined with the model's
    out-of-sample errors from historical days at the same time of year (all LDZs from the same day, so
    their errors stay correlated). The dotted lines show the weather-only spread for comparison. The
    errors widen the interval but don't move it — no bias correction yet.

    Demand is total − DM (the model's target), GWh/day. Actual demand appears as it is published:
    provisional (D+1) as open circles, closed out (D+6) as filled.
    """))
    return


@app.cell(hide_code=True)
def _(fch, fcm, mo):
    with mo.status.spinner(title="Loading forecasts and published demand"):
        runs = fch.wide(fcm.load_runs())
        actual = fcm.actuals()
    mo.stop(runs.empty, mo.callout(mo.md(
        "**No forecasts yet.** Run `python -m ldz_demand.models.forecast YYYY-MM-DD` for an ensemble run that "
        "has been built (`ens_ldz_daily`)."), kind="warn"))
    _dates = sorted(runs["run_date"].unique(), reverse=True)
    run_picker = mo.ui.dropdown(options={f"{d:%a %d %b %Y}": d for d in _dates}, value=f"{_dates[0]:%a %d %b %Y}",
                                label="Run (00z)")
    ldz_picker = mo.ui.dropdown(options=["GB", *sorted(set(runs["ldz"]) - {"GB"})], value="GB", label="LDZ")
    mo.hstack([run_picker, ldz_picker], justify="start", gap=2)
    return actual, ldz_picker, run_picker, runs


@app.cell(hide_code=True)
def _(actual, fch, ldz_picker, mo, run_picker, runs):
    _run = runs[runs["run_date"] == run_picker.value]
    mo.vstack([
        mo.md("## 1 · The forecast"),
        fch.fan(_run, actual, ldz_picker.value),
        mo.md("*The interval widens with lead time as the weather becomes less certain; a long tail on one "
              "side is the ensemble disagreeing about a cold (or mild) spell.*"),
    ])
    return


@app.cell(hide_code=True)
def _(actual, fch, ldz_picker, mo, runs):
    mo.vstack([
        mo.md(r"""
        ## 2 · How the forecast moved from run to run

        Each run's median for the same days. Runs that agree are steady weather; jumps are the forecast
        changing its mind as the day gets closer.
        """),
        fch.runs_compared(runs, actual, ldz_picker.value),
    ])
    return


@app.cell(hide_code=True)
def _(actual, fch, ldz_picker, mo, runs):
    _v = fch.verification(runs, actual, ldz_picker.value)
    if _v.empty:
        _out = mo.md("*No forecast day has published demand yet — demand for a gas day appears the next day "
                     "(provisional) and closes out six days later. A run is fully verified 14 days after it.*")
    else:
        _shown = _v.assign(**{
            "run_date": _v["run_date"].dt.strftime("%d %b"), "gas_day": _v["gas_day"].dt.strftime("%a %d %b"),
            "error %": _v["error %"].round(1), **{c: _v[c].round(0) for c in ("actual", "p50", "p10", "p90")},
            "provisional": _v["provisional"].map({True: "D+1", False: "D+6"})})
        _hit = _v["in 10–90%"].mean() * 100
        _out = mo.vstack([
            mo.ui.table(_shown, selection=None, show_column_summaries=False, page_size=15),
            mo.md(f"Inside the 10–90% interval on **{_hit:.0f}%** of {len(_v)} forecast days so far (target 80%), "
                  f"against {_v['in weather-only 10–90%'].mean() * 100:.0f}% for the weather-only interval."),
        ])
    mo.vstack([mo.md("## 3 · Verification, as demand is published"), _out])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4 · Notes

    - **Warm-up.** The model's effective temperature needs the days before each run. ERA5 is about five
      days behind, so those days come from earlier runs' ensemble mean (and a straight line across any gap);
      the model forgets fast, so this barely moves the forecast (0.2% on lead day 0 when tested).
    - **Shoulder months.** The model ran about 5% high in late September and early October 2026 — the
      season where it is weakest (`docs/results.md`). No correction is applied yet; the verification above
      is how to decide on one.
    - **Against National Gas.** Their day-ahead forecast is for total demand; like-for-like scoring with
      ours needs a winter of these runs (`docs/results.md`).
    - Run with `python -m ldz_demand.models.forecast YYYY-MM-DD`; stored in `demand_forecast_daily`.
    """)
    return


if __name__ == "__main__":
    app.run()
