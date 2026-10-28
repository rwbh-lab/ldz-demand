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
    _note = pages.snapshot_note()
    mo.vstack([
        mo.md(r"""
        # GB gas demand in the prompt window
        *The next two weeks of gas demand for Great Britain, as a range, from today's ECMWF ensemble run.*
        """),
        mo.accordion({"Contents": mo.Html(pages.contents_html(pages.INDEX))}),
    ] + ([mo.md(_note)] if _note else []), gap=0.5)
    return


@app.cell(hide_code=True)
def _(fch, fcm, mo):
    with mo.status.spinner(title="Loading the latest forecast"):
        runs = fch.wide(fcm.load_runs())
        actual = fcm.actuals()
    mo.stop(runs.empty, mo.callout(mo.md("**No forecasts yet.** See [Live forecasts](/live-forecasts)."), kind="warn"))
    latest = runs[runs["run_date"] == runs["run_date"].max()]
    _gb = latest[latest["ldz"] == "GB"].sort_values("gas_day")
    _tomorrow = _gb[_gb["lead_days"] == 1].iloc[0]
    _peak = _gb.loc[_gb["p50"].idxmax()]
    _data_to = actual[actual["ldz"] == "GB"]["gas_day"].max()
    mo.vstack([
        fch.fan(latest, actual, "GB"),
        mo.md(f"**Tomorrow** ({_tomorrow['gas_day']:%a %d %b}): {_tomorrow['p50']:,.0f} GWh/day, "
              f"10–90% {_tomorrow['p10']:,.0f}–{_tomorrow['p90']:,.0f} · **peak** of the fortnight: "
              f"{_peak['gas_day']:%a %d %b}, {_peak['p50']:,.0f} · actuals to {_data_to:%d %b %Y} · "
              "all LDZs on [Live forecasts](/live-forecasts)"),
    ])
    return actual, runs


@app.cell(hide_code=True)
def _(mo, ov, results):
    _h = ov.headline(results.load("experiments"))
    mo.vstack([
        mo.md(r"""
        ## 1 · Headline
        **A portfolio project:** the gas industry's weather-to-demand model rebuilt from free, public
        data, then run on every member of the weather ensemble to forecast demand two weeks ahead. Scored
        out of sample against the industry's own weather variable (the official CWV):
        """),
        mo.hstack([
            mo.stat(f"{_h.cold:+.0f}%".replace("-", "−"), label="Error on the coldest days",
                    caption="GB, against the official CWV"),
            mo.stat(f"{_h.all_days:+.0f}%".replace("-", "−"), label="Error over all days",
                    caption=f"better in {_h.ldz_better} of {_h.ldz_count} LDZs"),
            mo.stat(f"{_h.winter:+.0f}%".replace("-", "−"), label="Error in winter",
                    caption=f"{_h.days} days, scored forward"),
        ], justify="start", gap=1),
    ])
    return


@app.cell(hide_code=True)
def _(fch, mo, ov):
    with mo.status.spinner(title="Forecasting the sample run"):
        _runs, _actual = ov.worked_example()
    mo.vstack([
        mo.md(r"""
        ## 2 · It saw the cold coming
        The ECMWF run of **5 January 2025**, three days before that winter's coldest spell, put through the
        final model, with what happened laid over it. Demand climbs by about 750 GWh/day to the peak on
        9–10 January; 10 of the 14 days fall inside the 10–90% range.
        """),
        fch.fan(_runs, _actual, "GB"),
        mo.md("*This run is the [quick start](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_quickstart.md)'s "
              "sample: anyone can reproduce it in a few minutes.*"),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    def _card(title, line, link, path):
        return (f'<div style="border: 1px solid var(--border); border-radius: 8px; padding: 0.7em 0.9em">'
                f'<div style="font-weight: 600; color: var(--foreground)">{title}</div>'
                f'<div style="color: var(--muted-foreground); font-size: 0.9em">{line}</div>'
                f'<a href="{path}" style="font-size: 0.9em">{link} →</a></div>')

    _cards = [
        _card("The problem", "one weather station per LDZ", "National Gas data", "/ng-ldz-daily"),
        _card("The data", "three free sources, five years", "ERA5 weather", "/era5-weather"),
        _card("Weather per LDZ", "St Athan reads +0.85 °C in Nov", "LDZ weather", "/ldz-weather"),
        _card("The model", "the CWV refitted, all LDZs at once", "Model specification", "/model-specification"),
        _card("Tested properly", "forward, three winters", "Backtesting results", "/backtesting-results"),
    ]
    mo.vstack([
        mo.md("## 3 · What was done"),
        mo.Html('<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(10em, 1fr)); gap: 0.75em">'
                + "".join(_cards) + "</div>"),
    ])
    return


@app.cell(hide_code=True)
def _(actual, mo, ov, runs):
    _r = ov.live_record(runs, actual)
    _line = ("No published demand to check against yet." if _r is None else
             f"**{_r.runs} runs** since {_r.first_run:%d %b %Y} · **{_r.coverage:.0f}%** of {_r.days} forecast days "
             f"inside the 10–90% range (it should be about 80%) · lead day 1 off by **{_r.lead1_error:.1f}%** on "
             "average. A short record so far: the days overlap, so read it as it grows.")
    mo.md(f"""
    ## 4 · The live record, so far
    {_line} Every run and its verification: [Live forecasts](/live-forecasts).
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5 · How it's built
    - A **daily job** in Docker on a home server: download the ensemble, National Gas and ERA5 side by
      side, build the tables, forecast every new run.
    - **MySQL** for the tables; this site is a **static snapshot** of the dashboard, rebuilt from them.
    - **Tests on every push** (GitHub Actions); every step is on the [Project map](/project-map), and the
      code is on [GitHub](https://github.com/rwbh-lab/ldz-demand).

    ## 6 · Limits, and where next
    - **Weakest in the shoulder months** (spring and autumn, when heating switches on and off); **five
      years of data**, so the post-2022 change and the cold end can't be fully separated.
    - **Read on:** the [Summary](/summary) for the full story · the
      [decisions](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/decisions.md) behind each choice ·
      [run it yourself](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_quickstart.md) in a few minutes.
    """)
    return


if __name__ == "__main__":
    app.run()
