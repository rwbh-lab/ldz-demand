import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Backtesting results", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo
    import numpy as np

    from ldz_demand.charts import pages, style
    from ldz_demand.charts import results as rc
    from ldz_demand.models import results

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    RESULTS = "https://github.com/rwbh-lab/ldz-demand/blob/main/docs/results.md"
    WINTER = (11, 12, 1, 2, 3)
    Q = pages.Q
    return Q, RESULTS, WINTER, mo, np, pages, rc, results


@app.cell(hide_code=True)
def _(Q, RESULTS, mo, pages):
    pages.header("backtesting_results.py", mo.md(r"""
    # Backtesting results
    *How well the model does, against the official CWV and against National Gas's own forecasts.*
    """), mo.md(rf"""
    **Out of sample, the model's GB error is below the official CWV's on the same days, and well below
    National Gas's day-ahead forecasts in winter; its weak spot is the shoulder months.**

    - **Against the CWV**: the same regression, fed the official CWV instead.
    - **By month**: where in the year the errors are.
    - **Against National Gas**: their published day-ahead forecasts.
    - **Experiments** and **Still open**: what was tried, and what is left.

    Every score is out of sample: each gas year from 2023/24 is predicted by a model fitted only on the
    years before it. Scores are for **GB**, the sum of the 13 LDZs, on {Q} with actual weather (ERA5).
    The full write-up is in the [results]({RESULTS}).
    """), notation=True)
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
        f"(the [results](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/results.md)).\n\nError: `{load_error}`"), kind="warn"))
    return bench, daily, experiments, monthly


@app.cell(hide_code=True)
def _(WINTER, bench, daily, np):
    # the headline numbers, pooled over every scored day (GWh/day RMSE)
    def _rmse(err):
        return float(np.sqrt((err ** 2).mean()))

    _both = daily[daily["official"].notna()]
    _winter = bench[bench["gas_day"].dt.month.isin(WINTER)]
    score = dict(
        ours=_rmse(_both["final"] - _both["actual"]), official=_rmse(_both["official"] - _both["actual"]),
        ng_all=_rmse(bench["ng"] - bench["total"]), ours_all=_rmse(bench["ours"] - bench["total"]),
        ng_winter=_rmse(_winter["ng"] - _winter["total"]), ours_winter=_rmse(_winter["ours"] - _winter["total"]),
    )
    score["vs_cwv"] = score["ours"] / score["official"] - 1
    score["vs_ng"] = score["ours_all"] / score["ng_all"] - 1
    score["vs_ng_winter"] = score["ours_winter"] / score["ng_winter"] - 1
    return (score,)


@app.cell(hide_code=True)
def _(daily, mo, pages, rc, score):
    mo.vstack([
        mo.Html(pages.tiles([
            ("Error vs official CWV", f"{score['vs_cwv']:+.0%}".replace("-", "−"), "GB RMSE, same days, out of sample"),
            ("vs National Gas, winter", f"{score['vs_ng_winter']:+.0%}".replace("-", "−"), "RMSE, day-ahead, Nov–Mar"),
            ("vs National Gas, all days", f"{score['vs_ng']:+.0%}".replace("-", "−"), "RMSE, day-ahead"),
            ("Scored days", f"{len(daily):,}", "three forward gas years"),
        ])),
        mo.md(f"""{pages.heading("Against the CWV", f"{score['ours']:.1f} against {score['official']:.1f} GWh/day: "
                                                   f"{-score['vs_cwv']:.0%} lower error on the same days")}

    - The official CWV, run through the same demand regression, is the benchmark for the weather input
      itself.
    - It can't be scored on 2025/26: its definition changed on 1 October 2025, and there is no earlier
      year under the new one to fit on.
    - Error: mean absolute error per gas day, as a share of demand; RMSE in GWh/day.
    """),
        pages.md(rc.markdown_table(rc.headline(daily))),
        rc.actual_vs_predicted(daily),
        mo.md("*Click **Official CWV** in the legend to add it. Gaps: days not scored; until February 2024 "
              "mostly SE's repaired days, which train the model but aren't used to score it.*"),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(WINTER, mo, monthly, pages):
    measure = mo.ui.radio(options={"% error": "mape", "RMSE": "rmse", "Bias": "bias"}, value="% error",
                          label="Measure", inline=True)
    _m = monthly[monthly["model"] == "final"]
    _winter = _m[_m["month"].dt.month.isin(WINTER)]
    _shoulder = _m[_m["month"].dt.month.isin((4, 5, 6, 9, 10))]
    _avg = lambda g: (g["mape"] * g["days"]).sum() / g["days"].sum()  # noqa: E731 — day-weighted
    mo.vstack([
        mo.md(f"""{pages.heading("By month", f"About {_avg(_winter):.0f}% a day in winter, {_avg(_shoulder):.0f}% "
                                            "in the shoulder months")}

    - Winter is where the model is strongest: demand is high and weather drives most of it.
    - The shoulder months (April–June, September–October) are its weakest: demand there depends most on
      behaviour, when heating goes on and off.
    - In spring 2025 every model, the official CWV included, over-predicted.
    """),
        measure,
    ], gap=0.5)
    return (measure,)


@app.cell(hide_code=True)
def _(measure, monthly, rc):
    rc.errors_by_month(monthly, measure.value)
    return


@app.cell(hide_code=True)
def _(RESULTS, bench, mo, pages, rc, score):
    mo.vstack([
        mo.md(f"""{pages.heading("Against National Gas", f"{-score['vs_ng_winter']:.0%} less error than their day-ahead "
                                                        "in winter; mixed in summer")}

    - National Gas publishes its own demand forecast for each LDZ. Their first day-ahead issue (about
      13:00 the day before) against our model, both on **total** demand (ours plus the actual DM).
    - Summer is mixed: their error per day is lower in all three summers, but ours has the lower RMSE
      in two of them (fewer large misses).
    - **Not yet like for like.** Ours uses actual weather, theirs a forecast: a small difference one day
      ahead. And theirs also forecasts DM, which ours takes as given.
    - The fair test is our model on the ECMWF ensemble, issued at the same time: that needs a winter of
      ensemble runs.
    """),
        mo.accordion({"More detail": mo.md(rf"""
        Their forecast CWV is 0.31 °C off the actual on average, and removing the part of their error that
        follows it lowers their RMSE by only 1–13%. So most of the gap is not the weather forecast.
        ([results]({RESULTS}#against-national-gass-day-ahead-forecasts))
        """)}),
        pages.md(rc.markdown_table(rc.benchmark_table(bench))),
        rc.benchmark_by_month(bench),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(RESULTS, experiments, mo, pages, rc):
    mo.vstack([
        mo.md(f"""{pages.heading("Experiments", "One part changed at a time; recency weighting decided the final model")}

    - Each experiment changes one part of the model and keeps the rest; the best in each is in bold.
    - Held-out experiments predict each gas year from all the others; forward ones from the years before.
    - Scores within an experiment are on the same days; between experiments they aren't comparable.
    """),
        mo.accordion({"Every experiment (table)": mo.vstack([
            pages.md(rc.experiments_markdown(experiments)),
            mo.md("*GB RMSE in GWh/day (all days, winter Nov–Mar, the coldest 5% of days); error: mean absolute "
                  "error per gas day.*"),
        ]), "More detail": mo.md(rf"""
        Experiments 4 and 6 compare every model on the days they all share; with target A in the mix,
        only 2024/25, so a level per gas year comes out best there. The deciding comparison is target B
        alone over three forward years, where weighting recent years wins (48.2 vs 48.7 GWh/day;
        [results, experiment 6]({RESULTS}#experiment-6-target-a-vs-b)): that is the final model.
        """)}),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(mo, pages):
    mo.md(f"""{pages.heading("Still open", "The shoulder months, extreme cold, and the like-for-like test")}

    - **The shoulder months**, spring in particular: shared with the official CWV.
    - **Winter 2025/26** ran above every model on ordinary cold days; 2026/27 will tell whether demand is
      recovering further.
    - **The cold-weather upturn** sits on its cap in most LDZs; extreme cold is too rare in five years to
      calibrate.
    - **The daily min / max temperature**, on a definition shared by ERA5 and the ensemble.
    - **The like-for-like comparison** with National Gas, on the ensemble.
    """)
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer(definitions=True)
    return


if __name__ == "__main__":
    app.run()
