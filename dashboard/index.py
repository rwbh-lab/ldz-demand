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

    *Robert Hemming · working draft, October 2026*

    **Abstract.** Daily gas demand in each of Great Britain's 13 Local Distribution Zones (LDZs) is
    driven mainly by weather, and is forecast from a Composite Weather Variable (CWV) built from a
    single weather station per LDZ. This project rebuilds that weather input from gridded reanalysis
    (ERA5), averaged over each LDZ and weighted to where gas is used. It tests each variant against
    measured LDZ demand, then runs ECMWF ensemble forecasts through the fitted model to give
    probabilistic demand forecasts. Only free, public data is used.

    {pages.contents_markdown()}

    ---
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1 · Introduction
    *🚧 Why LDZ demand forecasting matters, how the official CWV works, and what this project changes.*

    ## 2 · Data
    *🚧 National Gas LDZ demand and offtakes; ERA5 hourly reanalysis; ECMWF ensemble forecasts;
    the gas day. Pages: [National Gas data](/ng-ldz-daily), [ERA5 weather](/era5-weather).*

    ## 3 · Mapping the LDZs
    *🚧 Four membership methods (local authority, Voronoi, hybrid, postcode-sampled), checked
    against measured demand. Page: [LDZ geography](/ldz-geography).*

    ## 4 · Weather per LDZ
    *🚧 Grid-cell weighting variants against the official one-station CWV. Page:
    [LDZ weather](/ldz-weather).*

    ## 5 · Demand model
    *🚧 Fitting LDZ demand to weather, per weather variant.*

    ## 6 · Ensemble forecasts
    *🚧 ECMWF ensemble members through the fitted model.*

    ## 7 · Validation
    *🚧 Skill against measured demand and against the official CWV.*

    ## 8 · Limitations and next steps
    *🚧*

    ## References and data sources
    *🚧 National Gas, ECMWF / Copernicus, ONS, DESNZ, Ordnance Survey; licences and attribution.*
    """)
    return


if __name__ == "__main__":
    app.run()
