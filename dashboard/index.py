import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Overview", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import pages, style

    theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return mo, pages


@app.cell(hide_code=True)
def _(mo, pages):
    mo.md(rf"""
    # Weather-driven gas demand for Great Britain's Local Distribution Zones

    *Robert Hemming · October 2026*

    **Abstract.** Daily gas demand in each of Great Britain's 13 Local Distribution Zones (LDZs) is driven
    mainly by the weather. The industry measures that weather with a Composite Weather Variable (CWV)
    built from one weather station per LDZ. This project rebuilds it from gridded reanalysis (ERA5),
    averaged over each LDZ and weighted to where gas is used, refits the CWV's form to five years of
    measured demand, and runs every member of the ECMWF ensemble through the fitted model to forecast
    demand two weeks ahead as a distribution rather than a single number. Out of sample, the model's GB
    error is 9% below the official CWV's over all days and 29% below it on the coldest days; in the
    winters scored, it is more accurate than National Gas's own published day-ahead forecasts.
    Everything uses free, public data.

    {pages.contents_html()}

    {pages.snapshot_note()}

    ---
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.hstack([
        mo.stat("−9%", label="Error vs the official CWV", caption="GB RMSE, all days, out of sample"),
        mo.stat("−29%", label="On the coldest days", caption="GB RMSE, coldest 5% of days"),
        mo.stat("1.9–2.2%", label="Winter error per gas day", caption="2024/25 and 2025/26 · National Gas 3.2–3.6%"),
        mo.stat("50 × 14", label="Members × days", caption="every ensemble run, as a demand distribution"),
    ], wrap=True, gap=1)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1 · Introduction

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
    [Project map](/project-map).

    ## 2 · Data

    Three free, public sources:

    - **National Gas** (data portal): daily LDZ demand and its daily- and non-daily-metered parts, the
      official CWV, the gas entering each LDZ from the national transmission system, and National Gas's
      own demand forecasts — a rolling five years, from October 2021. [National Gas data](/ng-ldz-daily)
    - **ERA5** (Copernicus): hourly reanalysis on a 0.25° grid — temperature, wind, solar radiation,
      precipitation. [ERA5 weather](/era5-weather)
    - **The ECMWF ensemble** (open data): each day's 00z run, 50 members, 15 days, cropped to GB as it
      downloads and archived daily on a home server.

    Everything is put on the **gas day**, 05:00 to 05:00 UK time.

    ## 3 · Pre-CWV models

    The steps that turn the published data into what the demand model needs.

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
    [Ensemble LDZ weather](/ensemble-forecasts)

    ## 4 · The CWV model

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

    What each part does, with its fitted values, is on the [Demand model](/demand-model) page; every
    choice, and the alternatives it beat, in `docs/decisions.md`.

    ## 5 · Results

    Every score is out of sample: each gas year is predicted only from the years before it.

    - **Against the official CWV** (the same regression, on the same days): GB error 46.2 against
      50.8 GWh/day over all days (−9%), 52.6 against 67.2 in winter (−22%), 65.8 against 92.3 on the
      coldest days (−29%). Better in 10 of the 13 LDZs.
    - **Against National Gas's published day-ahead forecasts**, on total demand: about level over all
      days (3.2–3.3% error per gas day against 3.1–3.6%), with 7–30% lower RMSE; in the two full winters
      scored, 1.9–2.2% against their 3.2–3.6%. They are better in summer — the shoulder months are this
      model's weakest.

    Not yet like for like: ours uses actual weather and theirs a day-ahead forecast (a small difference
    at one day ahead), and theirs also forecasts the daily-metered part. [Results](/results)

    ## 6 · Forecasts

    Each day's ensemble run goes through the fitted model member by member: 50 demand paths per LDZ for
    the next 14 days, and GB as their sum. The intervals add the model's own error to the weather's — the
    spread of the members says how uncertain the weather is, not how far the model can be off when the
    weather is known, and at short leads that is most of the uncertainty. Each forecast is made as it
    would have been issued, from only the data that existed on its run date, and verified as demand is
    published. [Demand forecasts](/demand-forecasts)

    ## 7 · Limitations

    - **Five years of demand** — the portal's rolling window. The 2022 change in behaviour and few cold
      winters fall inside it, so findings on seasonal behaviour and the cold end are provisional.
    - **The shoulder months** (spring and October) are the model's weakest; spring 2025 was missed by
      every model, the official CWV included.
    - **Extreme cold** is too rare in five years to calibrate the cold-weather upturn, which sits on its
      bound in most LDZs.
    - **The forecasts** need a winter of runs to be scored properly, and to compare with National Gas
      like for like.

    ## References and data sources

    - National Gas, *Gas Demand Forecasting Methodology* (2016); data portal, data.nationalgas.com.
    - Xoserve, *Composite Weather Variable* and *Seasonal Normal Composite Weather Variable* (September 2026).
    - Copernicus Climate Change Service, ERA5 hourly data on single levels (contains modified Copernicus
      Climate Change Service information).
    - ECMWF open data, ensemble forecasts (CC BY 4.0).
    - ONS, Index of Place Names and local authority boundaries (Open Government Licence; contains OS data
      © Crown copyright and database right). DESNZ, sub-national gas consumption (Open Government
      Licence). Ordnance Survey, Code-Point Open.
    - LDZ town lists: energybrokers.co.uk. Postcode checks: SGN and Wales & West Utilities.

    The method in full: `docs/methodology.md`; the choices: `docs/decisions.md`; the scores:
    `docs/results.md`.
    """)
    return


if __name__ == "__main__":
    app.run()
