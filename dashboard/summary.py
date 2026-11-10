import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Summary", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import pages, style

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    DECISIONS = "https://github.com/rwbh-lab/ldz-demand/blob/main/docs/decisions.md"

    def section(label: str, title: str, bullets: str, detail: str | None = None):
        """A section as its takeaway title (after a muted label, e.g. "Results |"), a few bullets, and the
        full text collapsed beneath."""
        body = [mo.md(f"{pages.heading(label, title)}\n\n{bullets}")]
        if detail:
            body.append(mo.accordion({"More detail": mo.md(detail)}))
        return mo.vstack(body, gap=0.25)
    return DECISIONS, mo, pages, section


@app.cell(hide_code=True)
def _(mo, pages):
    pages.header("summary.py", mo.md(r"""
    # Weather-driven gas demand for Great Britain's Local Distribution Zones
    """), mo.md(r"""
    **Weather averaged over each LDZ and weighted to where gas is used explains Great Britain's gas demand
    better than the industry's one station per LDZ: out of sample, GB error is 9% below the official
    Composite Weather Variable's (CWV) over all days, and 29% below on the coldest days.**

    The project rebuilds the CWV from gridded reanalysis (ERA5) for each of the 13 Local Distribution
    Zones (LDZs), refits its form to five years of measured demand, and runs every member of the ECMWF
    ensemble through the fitted model to forecast demand two weeks ahead as a range rather than a single
    number. In the winters scored it beats National Gas's published day-ahead forecasts; over the whole
    year it is level with them. Everything uses free, public data.
    """), notation=True)
    return


@app.cell(hide_code=True)
def _(mo, pages):
    mo.Html(pages.tiles([
        ("Error vs official CWV", "−9%", "GB RMSE, all days, out of sample"),
        ("On the coldest days", "−29%", "coldest 5% of days"),
        ("Winter error per day", "1.9–2.2%", "National Gas 3.2–3.6%"),
        ("Over the whole year", "3.2–3.3%", "National Gas 3.1–3.6%: level"),
    ]))
    return


@app.cell(hide_code=True)
def _(mo, pages):
    mo.Html(
        '<div style="border-left: 3px solid var(--border); padding: 0.2em 0 0.2em 0.9em; margin: 0.4em 0">'
        "<b>How this would be shown wrong.</b> Over winter 2026/27 (October to March), scored on closed-out "
        f"{pages.Q_at(6)}: if fewer than 7 or more than 9 GB days in 10 fall inside the day-ahead "
        f"{pages.P_RANGE} (it should be 8 in 10), or if the day-ahead error per gas day is not at least 25% "
        "below National Gas's on the same days (the backtest has it 30–45% below), the forecast claim fails."
        "</div>")
    return


@app.cell(hide_code=True)
def _(DECISIONS, mo):
    mo.md(rf"""
    ## Four choices carry the result

    - **The target is total minus daily-metered**, not the non-daily-metered that National Gas allocates. [P1]({DECISIONS}#p1-target-total--dm-not-ndm)
    - **The gas day's temperature weights the heating hours**: 9% lower error than a flat daily mean.
      [P5]({DECISIONS}#p5-gas-day-temperature-weighted-to-the-heating-hours)
    - **One seasonal shape shared by all 13 LDZs**, sized per LDZ, estimated from thirteen times the data.
      [C2]({DECISIONS}#c2-a-seasonal-shape-shared-by-all-ldzs)
    - **Recent years weighted more** (half-life one year), to follow the post-2022 fall in demand without
      hand-picked break dates. [C7]({DECISIONS}#c7-follow-behaviour-by-weighting-recent-years)
    """)
    return


@app.cell(hide_code=True)
def _(mo, section):
    mo.vstack([
        section("Introduction", "One weather station per LDZ misses where the gas is used", r"""
    - A January day takes nearly six times the gas of a summer one, mostly homes and small businesses heating.
    - The industry forecasts and allocates that demand per LDZ with the CWV, built from **one station per
      LDZ**: Heathrow for East Anglia, North Thames and South East alike.
    - A station can be unrepresentative: St Athan reads up to 0.85 °C warmer in November than where Wales
      South's gas is used.
    - The question here: how much better does weather over the whole LDZ, weighted to gas use, do? The full
      chain is on the [project map](/project-map).
    """, r"""
    Gas demand in Great Britain swings with the weather: a January day takes nearly six times the gas
    of a summer one. Most of that swing is non-daily-metered demand — homes and small businesses heating
    — and the industry forecasts it per LDZ from the **Composite Weather Variable**: a blend of
    temperature, wind, sunshine and a seasonal profile, bent so that demand responds to it in a straight
    line. National Gas forecasts demand with it; Xoserve allocates gas to shippers with it.

    The official CWV takes its weather from **one station per LDZ** — Heathrow for East Anglia, North
    Thames and South East alike. A station is one point, and not always a representative one: St Athan,
    on the coast, reads up to 0.85 °C warmer in November than the places where Wales South's gas is
    used. This project asks how much better demand can be explained, and forecast, with weather averaged
    over the whole LDZ and weighted to where the gas goes — and builds the forecasts that follow.

    The whole chain, from public data to a demand forecast, with the code behind each step, is on the
    [project map](/project-map).
    """),
        section("Data", "Three public sources, free data access, for every gas day", r"""
    - **National Gas**: daily LDZ demand, the official CWV and National Gas's own forecasts, a rolling five
      years from October 2021.
    - **ERA5**: hourly reanalysis on a 0.25° grid.
    - **The ECMWF ensemble**: each day's 00z run, 50 members, 15 days.
    - The weather is averaged over each **gas day**, 05:00 to 05:00 UK time, the day National Gas reports
      demand on, so weather and demand line up day for day.
    """, r"""
    - **National Gas** (data portal): daily LDZ demand and its daily- and non-daily-metered parts, the
      official CWV, the gas entering each LDZ from the national transmission system, and National Gas's
      own demand forecasts — a rolling five years, from October 2021. [National Gas data](/ng-ldz-daily)
    - **ERA5** (Copernicus): hourly reanalysis on a 0.25° grid — temperature, wind, solar radiation,
      precipitation. [ERA5 weather](/era5-weather)
    - **The ECMWF ensemble** (open data): each day's 00z run, 50 members, 15 days, cropped to GB as it
      downloads and archived daily on a home server.
    """),
        section("Pre-CWV models", "A target that isn't circular, an LDZ map, and weather weighted to gas use", r"""
    - **The target** is total demand minus daily-metered: the published non-daily-metered figure is
      allocated with the official CWV, so fitting to it would be circular.
    - A **31 GWh/day feed missing** from South East's total for 18 months is repaired for training and never
      used for scoring.
    - **The LDZ map** is built, since none is public: town lists, the ONS place index, and postcode checks.
    - **Weighting** to gas use and to the heating hours matters; the map method barely does (0.01–0.05 °C).
    """, r"""
    **The target.** The model predicts total LDZ demand minus daily-metered demand: homes and small
    business, plus unidentified gas. Not the published non-daily-metered figure — National Gas
    *allocates* that using the official CWV, so fitting a weather model to it would be circular. Checking
    the published totals against the gas metered into each LDZ found a 31 GWh/day feed missing from
    South East's total for 18 months (September 2022 – February 2024); those days are repaired for
    training and never used for scoring. [National Gas data, Part II](/ng-ldz-daily)

    **The LDZ map.** There is no public map of the LDZs, so one is built: town lists per LDZ, placed with
    the ONS place index, and — where a local authority is split between LDZs — postcodes sampled and
    checked against the gas networks' own postcode checkers. [LDZ geography](/ldz-geography)

    **LDZ weather.** Each LDZ's weather is a weighted average of the ERA5 grid cells over it, weighted by
    local gas use (DESNZ). The map method barely matters (0.01–0.05 °C day to day); the weighting matters
    more; the official stations differ most — by season, by up to 0.85 °C. The gas day's temperature
    weights the hours when homes heat: 06–09 and 16–22 count double, the night half.
    [LDZ weather](/ldz-weather)

    **Ensemble LDZ weather.** The same weights and gas-day rules for every ensemble member and lead day,
    so the forecasts see the same kind of weather the model was fitted on.
    [LDZ ECMWF ensemble](/ensemble-forecasts)
    """),
        section("CWV model", "The official CWV's structure, refitted per LDZ, with three changes", r"""
    - Kept: an effective temperature with a few days' memory, wind chill, solar, a seasonal shape, a summer
      cut-off and a cold-weather upturn; demand a straight line in the CWV plus calendar terms.
    - Changed: **a seasonal shape shared by all LDZs**, **the heating-hours temperature** (−9% error), and
      **recent years weighted more** (half-life one year).
    - What each part does: [model specification](/model-specification); every fitted value per LDZ:
      [model calibration](/model-calibration).
    """, r"""
    The official CWV's structure, refitted per LDZ to our weather: an effective temperature with a few
    days' memory, wind chill, solar, a seasonal shape, a summer cut-off and a cold-weather upturn. Demand
    is then a straight line in the CWV, plus day of week, bank holidays and the Christmas period. Three
    choices carry most of the improvement:

    - **A seasonal shape shared by all 13 LDZs**, in place of the official seasonal profile (which isn't
      public): one smooth shape through the year, sized per LDZ, so it is estimated from thirteen times
      the data.
    - **The heating-hours temperature**: 9% lower error than a flat daily mean, and the gain survives
      the ensemble's 3- and 6-hourly steps.
    - **Recent years weighted more** (half-life one year), so the model follows the fall in demand after
      the 2022 price shock, and the partial recovery since, without hand-picked break dates.

    What each part does is on [model specification](/model-specification), and how it is fitted, with
    every value per LDZ, on [model calibration](/model-calibration); every
    choice, and the alternatives it beat, in the [decisions](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/decisions.md).
    """),
        section("Results", "9% below the official CWV, 29% on the coldest days; beats National Gas in winter", r"""
    - Every score is out of sample: each gas year is predicted only from the years before it.
    - **Against the official CWV** (same regression, same days): GB error 46.2 against 50.8 GWh/day (−9%),
      −22% in winter, −29% on the coldest days. Better in 10 of the 13 LDZs.
    - **Against National Gas's day-ahead forecasts**: 1.9–2.2% error per day against 3.2–3.6% in the two
      winters scored; level over the year; behind in summer and the shoulder months.
    - Not yet like for like: ours uses actual weather, theirs a forecast. [Backtesting results](/backtesting-results)
    """, r"""
    - **Against the official CWV** (the same regression, on the same days): GB error 46.2 against
      50.8 GWh/day over all days (−9%), 52.6 against 67.2 in winter (−22%), 65.8 against 92.3 on the
      coldest days (−29%). Better in 10 of the 13 LDZs.
    - **Against National Gas's published day-ahead forecasts**, on total demand: about level over all
      days (3.2–3.3% error per gas day against 3.1–3.6%), with 7–30% lower RMSE; in the two full winters
      scored, 1.9–2.2% against their 3.2–3.6%. They are better in summer — the shoulder months are this
      model's weakest.

    Not yet like for like: ours uses actual weather and theirs a day-ahead forecast (a small difference
    at one day ahead), and theirs also forecasts the daily-metered part. [Backtesting results](/backtesting-results)
    """),
        section("Forecasts", "Two weeks ahead as a range, with the model's own error added", r"""
    - Each day's ensemble run goes through the model member by member: 50 demand paths per LDZ for 14 days,
      GB as their sum.
    - The intervals add the model's own error to the weather's spread; at short leads the model's error is
      most of the uncertainty.
    - Each forecast uses only the data that existed on its run date, and is verified as demand is
      published. [Live forecasts](/live-forecasts)
    """, r"""
    Each day's ensemble run goes through the fitted model member by member: 50 demand paths per LDZ for
    the next 14 days, and GB as their sum. The intervals add the model's own error to the weather's — the
    spread of the members says how uncertain the weather is, not how far the model can be off when the
    weather is known, and at short leads that is most of the uncertainty. Each forecast is made as it
    would have been issued, from only the data that existed on its run date, and verified as demand is
    published. [Live forecasts](/live-forecasts)
    """),
        section("Limitations", "Five years of data leave the cold end and the shoulder months provisional", r"""
    - **Five years of demand**, the portal's rolling window: the 2022 change in behaviour and few cold
      winters fall inside it, so findings on seasonal behaviour and the cold end are provisional.
    - **The shoulder months** (spring and October) are the model's weakest; spring 2025 was missed by
      every model, the official CWV included.
    - **Extreme cold** is too rare in five years to calibrate the cold-weather upturn, which sits on its
      bound in most LDZs.
    - **The forecasts** need a winter of runs to be scored properly, and to compare with National Gas
      like for like.
    """),
    ], gap=1.25)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.accordion({"References and data sources": mo.md(r"""
    - National Gas, *Gas Demand Forecasting Methodology* (2016); data portal, data.nationalgas.com.
    - Xoserve, *Composite Weather Variable* and *Seasonal Normal Composite Weather Variable* (September 2026).
    - Copernicus Climate Change Service, ERA5 hourly data on single levels (contains modified Copernicus
      Climate Change Service information).
    - ECMWF open data, ensemble forecasts (CC BY 4.0).
    - ONS, Index of Place Names and local authority boundaries (Open Government Licence; contains OS data
      © Crown copyright and database right). DESNZ, sub-national gas consumption (Open Government
      Licence). Ordnance Survey, Code-Point Open.
    - LDZ town lists: energybrokers.co.uk. Postcode checks: SGN and Wales & West Utilities.

    The method in full: the [methodology](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/methodology.md); the choices: the [decisions](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/decisions.md); the scores:
    the [results](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/results.md).
    """)})
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer(definitions=True)
    return


if __name__ == "__main__":
    app.run()
