import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Backtesting results", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import results as rc
    from ldz_demand.charts import style
    from ldz_demand.models import results

    theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return mo, rc, results


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.charts import pages as _pages

    _pages.header("backtesting_results.py", mo.md(r"""
    # Backtesting results
    *How well the model does, against the official CWV and against National Gas's own forecasts.*
    """), mo.md(r"""
    Every score here is **out of sample**: each gas year from 2023/24 is predicted by a model fitted only on
    the years before it — as a forecaster would have had to. Scores are for **GB**, the sum of the 13
    LDZs, on days every LDZ has, with actual weather (ERA5). How the model works is on the
    [Model specification](/model-specification) page; the reasoning behind each choice is in `docs/decisions.md`, and
    the full write-up in `docs/results.md`.
    """))
    return


@app.cell(hide_code=True)
def _(mo, results):
    try:
        daily, monthly = results.load("final_daily"), results.load("final_monthly")
        bench, experiments = results.load("benchmark"), results.load("experiments")
        load_error = None
    except Exception as exc:
        load_error = exc
    mo.stop(load_error is not None, mo.callout(mo.md(
        "**No results bundle.** Run the experiments and then `python -m ldz_demand.models.results` "
        f"(`docs/results.md`).\n\nError: `{load_error}`"), kind="warn"))
    return bench, daily, experiments, monthly


@app.cell(hide_code=True)
def _(daily, mo, rc):
    mo.vstack([
        mo.md(r"""
        ## 1 · Against the official CWV

        The official CWV, run through the same demand regression, is the benchmark for the weather input
        itself. It can't be scored on 2025/26: its definition changed on 1 October 2025, and there is no
        earlier year under the new one to fit on.
        """),
        mo.md(rc.markdown_table(rc.headline(daily))),
        mo.md("*RMSE in GWh/day; error: mean absolute error per gas day, as a share of demand (total − DM).*"),
        rc.actual_vs_predicted(daily),
        mo.md("*Click **Official CWV** in the legend to add it. Gaps: days not scored — until February 2024 "
              "mostly SE's repaired days, which train the model but aren't used to score it.*"),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    measure = mo.ui.radio(options={"% error": "mape", "RMSE": "rmse", "Bias": "bias"}, value="% error",
                          label="Measure", inline=True)
    mo.vstack([
        mo.md(r"""
        ## 2 · Errors by month

        Winter is where the model is strongest — demand is high and weather drives most of it. The
        shoulder months (April – June, October) are its weakest: demand there depends most on behaviour
        (when heating goes on and off), and in spring 2025 every model, the official CWV included,
        over-predicted.
        """),
        measure,
    ])
    return (measure,)


@app.cell(hide_code=True)
def _(measure, monthly, rc):
    rc.errors_by_month(monthly, measure.value)
    return


@app.cell(hide_code=True)
def _(bench, mo, rc):
    mo.vstack([
        mo.md(r"""
        ## 3 · Against National Gas's forecasts

        National Gas publishes its own demand forecast for each LDZ. Their first day-ahead issue (about
        13:00 the day before) against our model, both on **total** demand (ours plus the actual DM).
        """),
        mo.md(rc.markdown_table(rc.benchmark_table(bench))),
        rc.benchmark_by_month(bench),
        mo.md(r"""
        **Not yet like for like, in two directions.** Ours uses actual weather and theirs a day-ahead
        forecast — a small difference at one day ahead: their forecast CWV is 0.31 °C off the actual on
        average, and removing the part of their error that follows it lowers their RMSE by only 1–13%. And
        theirs also forecasts DM, which ours takes as given. The fair test is our model on the ECMWF
        ensemble, issued at the same time; that needs an ensemble archive covering at least one winter.
        """),
    ])
    return


@app.cell(hide_code=True)
def _(experiments, mo, rc):
    mo.vstack([
        mo.md(r"""
        ## 4 · Every experiment

        Each experiment changes one part of the model and keeps the rest; the best in each is in bold.
        Held-out experiments predict each gas year from all the others; forward ones from the years before
        it. Scores within an experiment are on the same days; between experiments they aren't comparable.
        """),
        mo.md(rc.experiments_markdown(experiments)),
        mo.md("*GB RMSE in GWh/day (all days, winter Nov–Mar, the coldest 5% of days); error: mean absolute "
              "error per gas day.*"),
        mo.md("Experiments 4 and 6 compare every model on the days they all share — with target A in the mix, "
              "only 2024/25 — so a level per gas year comes out best there. The deciding comparison is target B "
              "alone over three forward years, where weighting recent years wins (48.2 vs 48.7 GWh/day; "
              "`docs/results.md`, experiment 6): that is the final model."),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5 · Still open

    - **The shoulder months**, spring in particular — shared with the official CWV.
    - **Winter 2025/26** ran above every model on ordinary cold days; 2026/27 will tell whether demand is
      recovering further.
    - **The cold-weather upturn** sits on its bound in the final fit; extreme cold is too rare in five
      years to calibrate.
    - **The daily min / max temperature**, on a definition shared by ERA5 and the ensemble.
    - **The like-for-like comparison** with National Gas, on the ensemble.
    """)
    return


if __name__ == "__main__":
    app.run()
