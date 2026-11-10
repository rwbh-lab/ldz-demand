import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Overview", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import forecasts as fch
    from ldz_demand.charts import overview as ov
    from ldz_demand.charts import pages, style
    from ldz_demand.models import forecast as fcm
    from ldz_demand.models import results

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return fch, fcm, mo, ov, pages, results


@app.cell(hide_code=True)
def _(mo, pages):
    pages.header(pages.INDEX, mo.md(r"""
    # Great Britain gas demand in the prompt window
    *The next two weeks of gas demand for Great Britain, as a range, from today's ECMWF ensemble run.*
    """), mo.md(r"""
    **The gas industry's weather-to-demand model, rebuilt from free public data and run on all 50 members
    of the ECMWF ensemble: two weeks of demand as a range, every day.**

    - **Forecast**: the latest run, for GB.
    - **Headline**: how the model scores against the industry's own weather variable.
    - **Worked example**: a run three days before the coldest spell of winter 2024/25.
    - **What was done**, **Live record**, **How it's built** and **Limits**: the rest in brief.
    """), notation=True)
    return


@app.cell(hide_code=True)
def _(fch, fcm, mo, ov, pages):
    with mo.status.spinner(title="Loading the latest forecast"):
        runs = fch.wide(fcm.load_runs())
        mo.stop(runs.empty, mo.callout(mo.md("**No forecasts yet.** See [live forecasts](/live-forecasts)."),
                                       kind="warn"))
        actual = fcm.actuals(since=runs["run_date"].min())
    latest = runs[runs["run_date"] == runs["run_date"].max()]
    _o = ov.outlook(latest)
    _data_to = actual[actual["ldz"] == "GB"]["gas_day"].max()
    _t = _o.tomorrow
    _gb = latest[latest["ldz"] == "GB"]
    _first, _last = _gb["gas_day"].min(), _gb["gas_day"].max()
    _period = _gb.dropna(subset=["period_p50"]) if "period_p50" in _gb else _gb.iloc[0:0]
    if _period.empty:  # runs forecast before the period statistics existed: the mean median, no range yet
        _mean = (f"{_gb['p50'].mean():,.0f}", "range from the next run")
    else:
        _r = _period.iloc[0]
        _mean = (f"{_r['period_p50']:,.0f}", f"{pages.P_RANGE} {_r['period_p10']:,.0f}–{_r['period_p90']:,.0f}")
    mo.vstack([
        # the takeaway as the section heading, so it wraps on a phone (a Plotly title doesn't)
        mo.md(pages.heading("Forecast", _o.takeaway)),
        # the result: three numbers, wrapping on a narrow screen, then the chart that shows them
        mo.Html(pages.tiles([
            (f"Tomorrow, {_t['gas_day']:%a %d %b}", f"{_t['p50']:,.0f}",
             f"{pages.P_RANGE} {_t['p10']:,.0f}–{_t['p90']:,.0f}", "GWh/day"),
            (f"Mean, {_first:%a %d} – {_last:%a %d %b}", _mean[0], _mean[1], "GWh/day"),
            # placeholder until the seasonal normal exists; then: tomorrow against normal
            (f"Range by {_o.last['gas_day']:%a %d %b}", f"±{_o.spread_last:.0f}%",
             f"half of {pages.P_RANGE} · ±{_o.spread_tomorrow:.0f}% tomorrow"),
        ])),
        fch.fan(latest, actual, "GB"),
        mo.md(f"<small>Published {pages.Q} to {_data_to:%d %b %Y} (National Gas) · every LDZ, "
              "each run and how they verify: [live forecasts](/live-forecasts)</small>"),
    ], gap=0.75)
    return actual, runs


@app.cell(hide_code=True)
def _(mo, ov, pages, results):
    _h = ov.headline(results.load("experiments"))
    _minus = lambda x: f"{x:+.0f}%".replace("-", "−")  # noqa: E731
    mo.vstack([
        mo.md(f"""{pages.heading("Headline", f"{-_h.all_days:.0f}% less error than the official CWV, "
                                           f"{-_h.cold:.0f}% on the coldest days")}

    - Scored out of sample, each gas year predicted by a model fitted only on the years before it,
      against the industry's own weather variable (the official CWV) in the same demand model.
    - Error is GB RMSE, GWh/day; the detail is on [backtesting results](/backtesting-results).
    """),
        mo.Html(pages.tiles([
            ("Error on the coldest days", _minus(_h.cold), "GB, against the official CWV"),
            ("Error over all days", _minus(_h.all_days), f"better in {_h.ldz_better} of {_h.ldz_count} LDZs"),
            ("Error in winter", _minus(_h.winter), f"{_h.days} days, scored forward"),
        ])),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(fch, mo, ov, pages):
    with mo.status.spinner(title="Forecasting the sample run"):
        _runs, _actual = ov.worked_example()
    _v = fch.verification(_runs, _actual, "GB")
    mo.vstack([
        mo.md(f"""{pages.heading("Worked example", "The 5 Jan 2025 run saw the coldest spell coming, three days out")}

    - That day's ECMWF run, put through the final model, with what happened laid over it.
    - Demand climbs by about 750 GWh/day to the peak on 9–10 January; {int(_v["in 10–90%"].sum())} of the
      {len(_v)} days fall inside {pages.P_RANGE}.
    """),
        fch.fan(_runs, _actual, "GB"),
        mo.md("*This run is the [quick start](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_quickstart.md)'s "
              "sample: anyone can reproduce it in a few minutes.*"),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(mo, pages):
    def _card(title, line, link, path):
        return (f'<div style="border: 1px solid var(--border); border-radius: 8px; padding: 0.7em 0.9em">'
                f'<div style="font-weight: 600; color: var(--foreground)">{title}</div>'
                f'<div style="color: var(--muted-foreground); font-size: 0.9em">{line}</div>'
                f'<a href="{path}" style="font-size: 0.9em">{link} →</a></div>')

    _cards = [
        _card("The problem", "one weather station per LDZ", "national gas data", "/ng-ldz-daily"),
        _card("The data", "three free sources, five years", "ERA5 weather", "/era5-weather"),
        _card("Weather per LDZ", "St Athan reads ~0.8 °C warm in Nov", "ldz weather", "/ldz-weather"),
        _card("The model", "the CWV refitted, all LDZs at once", "model specification", "/model-specification"),
        _card("Tested properly", "forward, three winters", "backtesting results", "/backtesting-results"),
        _card("Checked live", "every run scored as demand closes out", "error analysis", "/error-analysis"),
    ]
    mo.vstack([
        mo.md(pages.heading("What was done", "Free data, weather per LDZ, a refitted CWV, tested forward and live")),
        mo.Html('<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(10em, 1fr)); gap: 0.75em">'
                + "".join(_cards) + "</div>"),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(actual, mo, ov, pages, runs):
    _r = ov.live_record(runs, actual)
    if _r is None:
        _statement, _body = "Waiting for closed-out demand", "- No closed-out demand to check against yet."
    else:
        _statement = (f"{_r.coverage:.0f}% of closed-out days inside {pages.P_RANGE} (target 80%); "
                      f"day-ahead off {_r.lead1_error:.1f}%")
        _body = f"""- **{_r.runs} runs** since {_r.first_run:%d %b %Y}, scored on {_r.days} closed-out forecast days ({pages.Q_at(6)}).
    - A short record so far: each day is scored by up to 14 runs, so the days overlap. The test, and the
      weather forecast on its own, are on [error analysis](/error-analysis).
    - Every run, LDZ by LDZ: [live forecasts](/live-forecasts)."""
    mo.md(f"""{pages.heading("Live record", _statement)}

    {_body}
    """)
    return


@app.cell(hide_code=True)
def _(mo, pages):
    mo.md(f"""{pages.heading("How it's built", "A daily job on a home server, a database, and a static snapshot")}

    - A **daily job** in Docker on a home server: download the ensemble, National Gas and ERA5 side by
      side, build the tables, forecast every new run.
    - **MySQL** for the tables; this site is a **static snapshot** of the dashboard, rebuilt from them.
    - **Tests on every push** (GitHub Actions); every step is on the [project map](/project-map), and the
      code is on [GitHub](https://github.com/rwbh-lab/ldz-demand).

    {pages.heading("Limits", "Weakest in spring and autumn; five years of data")}

    - **Weakest in the shoulder months**: spring and autumn, when heating switches on and off.
    - **Five years of data**, so the post-2022 change and the cold end can't be fully separated.
    - **Read on:** the [summary](/summary) for the full story · the
      [decisions](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/decisions.md) behind each choice ·
      [run it yourself](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_quickstart.md) in a few minutes.
    """)
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer(definitions=True)
    return


if __name__ == "__main__":
    app.run()
