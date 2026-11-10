import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Live forecasts", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import forecasts as fch
    from ldz_demand.charts import pages
    from ldz_demand.charts import run_history as rh
    from ldz_demand.charts import style
    from ldz_demand.models import forecast as fcm

    RECENT_RUNS = 7  # runs shown by default (all of them locally, on request)
    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return RECENT_RUNS, fch, fcm, mo, pages, rh


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.charts import pages as _pages

    _pages.header("live_forecasts.py", title=mo.md(r"""
    # Live forecasts
    *Gas demand for the next two weeks, per LDZ, from the ECMWF ensemble.*
    """), intro=mo.md(r"""
    **Two weeks of demand per LDZ as a range, with the model's own error added to the weather's.** Each
    day's 00z ensemble gives 50 equally likely versions of the next 15 days' weather; each goes through the
    [demand model](/model-specification), giving 50 demand paths per LDZ for lead days 0–13. GB is their
    sum, member by member.

    - **Forecast**: the latest run, with published demand as it arrives.
    - **Run to run**: how the forecast for the same days moved.
    - **Run history**: four views of the runs' ranges, while we choose one.
    - **Verification**: how often demand landed inside the range (the detail is on [error analysis](/error-analysis)).
    """), notation=True)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.accordion({"How the ranges are built": mo.md(r"""
    **The intervals include the model's own error, not just the weather's.** On its own, the spread of
    the 50 members is far too narrow at short leads: it says how uncertain the weather is, not how far
    the model can be off when the weather is known. So each member is combined with the model's
    out-of-sample errors from historical days at the same time of year (all LDZs from the same day, so
    their errors stay correlated). The dotted lines show the weather-only spread for comparison. The
    errors widen the interval but don't move it — no bias correction yet.

    Demand <i>Q</i> is total − DM (the model's target), GWh/day. Published demand appears as a short tick on
    a bar for the figure's own P<sub>10</sub>–P<sub>90</sub> range. Provisional figures, <i>Q</i><sub>D+1</sub>, are drawn
    fainter, and their range is how far <i>Q</i><sub>D+1</sub> has usually moved by the closed-out <i>Q</i><sub>D+6</sub>; closed-out figures carry
    the ±1% metering tolerance ([methodology §8](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/methodology.md#8-forecasting)).
    """)})
    return


@app.cell(hide_code=True)
def _(RECENT_RUNS, fch, fcm, mo):
    with mo.status.spinner(title="Loading forecasts and published demand"):
        runs = fch.wide(fcm.load_runs())
        mo.stop(runs.empty, mo.callout(mo.md(
            "**No forecasts yet.** Run `python -m ldz_demand.models.forecast YYYY-MM-DD` for an ensemble run "
            "that has been built (`ens_ldz_daily`)."), kind="warn"))
        actual = fcm.actuals(since=runs["run_date"].min())
    ldz_picker = mo.ui.dropdown(options=["GB", *sorted(set(runs["ldz"]) - {"GB"})], value="GB", label="LDZ")
    all_runs = mo.ui.switch(value=False, label=f"All {runs['run_date'].nunique()} runs (last {RECENT_RUNS} shown)")
    return actual, all_runs, ldz_picker, runs


@app.cell(hide_code=True)
def _(RECENT_RUNS, all_runs, ldz_picker, mo, pages, runs):
    _dates = sorted(runs["run_date"].unique(), reverse=True)
    recent = runs if all_runs.value else runs[runs["run_date"].isin(_dates[:RECENT_RUNS])]
    run_picker = mo.ui.dropdown(options={f"{d:%a %d %b %Y}": d for d in sorted(recent["run_date"].unique(), reverse=True)},
                                value=f"{_dates[0]:%a %d %b %Y}", label="Run (00z)")
    # the snapshot's controls are fixed, so the switch would do nothing there
    mo.hstack([run_picker, ldz_picker] + ([] if pages.is_snapshot() else [all_runs]), justify="start", gap=2, wrap=True)
    return recent, run_picker


@app.cell(hide_code=True)
def _(actual, fch, ldz_picker, mo, pages, run_picker, runs):
    from ldz_demand.charts import overview as _ov

    _run = runs[runs["run_date"] == run_picker.value]
    _t = _ov.outlook(_run, ldz_picker.value).takeaway
    mo.vstack([
        mo.md(pages.heading("Forecast", f"{ldz_picker.value} demand {_t[len('Demand '):]}" if _t.startswith("Demand ")
                            else f"{ldz_picker.value}: {_t}")),
        fch.fan(_run, actual, ldz_picker.value),
        mo.md("*The interval widens with lead time as the weather becomes less certain; a long tail on one "
              "side is the ensemble disagreeing about a cold (or mild) spell.*"),
    ])
    return


@app.cell(hide_code=True)
def _(actual, fch, ldz_picker, mo, pages, recent):
    mo.vstack([
        mo.md(f"""{pages.heading("Run to run", "Runs that agree are steady weather; jumps are the forecast changing its mind")}

    - Each run's median for the same gas days, as each day gets closer.
    """),
        fch.runs_compared(recent, actual, ldz_picker.value),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    history_view = mo.ui.dropdown(options={
        "B · One gas day, densities (ridgeline)": "ridgeline",
        "C · All runs blended into one forecast": "blend",
        "D · Every run × every gas day (heatmap)": "heatmap",
        "E · Chance of exceeding a level": "exceedance",
    }, value="B · One gas day, densities (ridgeline)", label="View")
    return (history_view,)


@app.cell(hide_code=True)
def _(actual, history_view, ldz_picker, mo, pages, rh, runs):
    _ldz = ldz_picker.value
    _days = rh.target_days(runs, _ldz)
    _default = rh.default_target_day(runs, actual, _ldz)
    target_day = mo.ui.dropdown(options={f"{d:%a %d %b %Y}": d for d in _days}, value=f"{_default:%a %d %b %Y}",
                                label="Gas day")
    weighting = mo.ui.dropdown(options=rh.WEIGHTINGS, value=next(iter(rh.WEIGHTINGS)), label="Weighting")
    heat_measure = mo.ui.dropdown(options=rh.HEATMAP_MEASURES, value=next(iter(rh.HEATMAP_MEASURES)), label="Colour by")
    heat_rows = mo.ui.dropdown(options=rh.HEATMAP_ROWS, value="Run", label="Rows")
    _t = rh.default_threshold(runs, _ldz)
    _step = 50 if _t > 500 else 5
    threshold = mo.ui.number(start=0, stop=_t * 3, step=_step, value=_t, label="Level (GWh/day)")
    _controls = {"ridgeline": [target_day], "blend": [weighting],
                 "heatmap": [heat_measure, heat_rows], "exceedance": [threshold]}[history_view.value]
    mo.vstack([
        mo.md(f"""{pages.heading("Run history", "Four views of the runs' ranges, side by side while we choose one 🚧")}

    - *Run to run* shows only each run's median; these show the ranges as well, each a different way in.
    """),
        mo.hstack([history_view, *_controls], justify="start", gap=2, wrap=True),
    ])
    return heat_measure, heat_rows, target_day, threshold, weighting


@app.cell(hide_code=True)
def _(actual, heat_measure, heat_rows, history_view, ldz_picker, mo, recent, rh, run_picker, runs, target_day, threshold,
      weighting):
    _ldz, _view = ldz_picker.value, history_view.value
    if _view == "ridgeline":
        _out = [rh.ridgeline(runs, actual, _ldz, target_day.value), mo.md(
            "*The same runs as density curves, so the shape shows as well as the width: a cold tail growing "
            "or fading, two camps of members. The curves are rebuilt from the seven stored percentiles, so "
            "the far tails are an approximation.*")]
    elif _view == "blend":
        _how = weighting.value
        _label = next(k for k, v in rh.WEIGHTINGS.items() if v == _how)
        _b = rh.blend(runs, _ldz, run_picker.value, _how)
        _s = rh.blend_score(runs, actual, _ldz, _how)
        _score = "" if _s is None else (
            f"Scored over {_s['days']} forecast days with closed-out (D+6) demand, each blended as of its own run: "
            f"**{_s['blend_cover']:.0f}%** inside the blend's P<sub>10</sub>–P<sub>90</sub> (single run: {_s['single_cover']:.0f}%; "
            f"target 80%), median off by **{_s['blend_mae']:,.0f}** GWh on average (single run: "
            f"{_s['single_mae']:,.0f}), mean P<sub>10</sub>–P<sub>90</sub> width {_s['blend_width']:,.0f} (single run: "
            f"{_s['single_width']:,.0f}).")
        _out = [rh.blend_chart(_b, actual, _ldz, run_picker.value, _label), mo.md(
            "*A lagged ensemble: for each gas day of the selected run, every earlier run that also covered the "
            "day, mixed as one distribution. The weights are rescaled over the runs that exist, so the last "
            "days (one or two runs) are close to the newest run alone; hover for the run count and the newest "
            "run's share. The grey lines are the selected run on its own.*"), mo.md(_score)]
    elif _view == "heatmap":
        _e = rh.error_by_lead(runs, actual, _ldz)
        _bias = "" if _e.empty else "Median error so far, by lead: " + " · ".join(
            f"**{band}** {r['mean']:+.1f}% (±{r['mae']:.1f}% typical, {int(r['days'])} days)" for band, r in _e.iterrows()) + "."
        _out = [rh.run_heatmap(runs, actual, _ldz, heat_measure.value, heat_rows.value), mo.md(
            "*Every forecast at once. Coloured by error, red is a median above what was published and blue "
            "below; blank cells wait for the closed-out (D+6) figure. With rows by **run**, read down a column for "
            "one day's forecasts as it approached. With rows by **days ahead**, a row of one colour is a bias "
            "at that lead, and a column of one colour is a day every run missed the same way: the weather, or "
            "something the model doesn't see.*"), mo.md(_bias)]
    else:
        _out = [rh.exceedance(recent, actual, _ldz, threshold.value), mo.md(
            "*The chance of demand above the level for each gas day, one line per run shown in section 2, faded with age. The "
            "markers are what happened: at 100% where demand went over, at 0% where it did not. A trader's "
            "reading of the same forecasts (plan step 6).*")]
    mo.vstack(_out)
    return


@app.cell(hide_code=True)
def _(actual, fch, ldz_picker, mo, pages, runs):
    # the headline only; the scoring itself is on Error analysis
    _v = fch.verification(runs, actual, ldz_picker.value)
    _scored = _v[~_v["provisional"]] if not _v.empty else _v
    if _scored.empty:
        _statement = "Waiting for closed-out demand"
    else:
        _statement = (f"{_scored['in 10–90%'].mean():.0%} of closed-out days inside {pages.P_RANGE} (target 80%); "
                      f"weather alone {_scored['in weather-only 10–90%'].mean():.0%}")
    mo.md(f"""{pages.heading("Verification", _statement)}

    - Only closed-out (D+6) days are scored: the provisional D+1 figure can be far off for some LDZs, and
      GB inherits it. A run is fully scored 14 days after it.
    - The test of that figure, the bias, the tails and the weather forecast on its own are on
      [error analysis](/error-analysis).
    """)
    return


@app.cell(hide_code=True)
def _(mo, pages):
    mo.md(f"""{pages.heading("Notes", "Warm-up, the shoulder months, and the National Gas comparison")}

    - **Warm-up.** The model's effective temperature needs the days before each run. ERA5 is six
      days behind, so those days come from earlier runs' ensemble mean (and a straight line across any gap);
      the model forgets fast, so this barely moves the forecast (0.2% on lead day 0 when tested).
    - **Shoulder months.** The model ran about 5% high in late September and early October 2026 — the
      season where it is weakest ([results, summer follow-up](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/results.md#follow-up-summer-and-the-shoulder-months)). No correction is applied yet; the verification above
      is how to decide on one.
    - **Against National Gas.** Their day-ahead forecast is for total demand; like-for-like scoring with
      ours needs a winter of these runs ([results](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/results.md#against-national-gass-day-ahead-forecasts)).
    - Run with `python -m ldz_demand.models.forecast YYYY-MM-DD`; stored in `demand_forecast_daily`.
    """)
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer(definitions=True)
    return


if __name__ == "__main__":
    app.run()
