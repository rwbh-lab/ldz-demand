import marimo

__generated_with = "0.25.1"
app = marimo.App(width="full", app_title="LDZ demand · Project map", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import project_map as pmap
    from ldz_demand.charts import style

    theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return mo, pmap, theme


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages

    _pages.nav("project_map.py")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Project map
    *From public data to a demand forecast: what feeds what, and the code behind each step.*

    Read top to bottom. **Sources** are downloaded and archived as **datasets**. The **pre-CWV models**
    turn those into what the demand model needs — a clean target, and weather for each LDZ, weighted
    by where gas is used. The **CWV model** turns that weather into a composite weather variable and
    demand, and its **outputs** are scored predictions, the benchmark against National Gas, and (next)
    demand forecasts from the ECMWF ensemble. The strip underneath is used throughout.
    """)
    return


@app.cell(hide_code=True)
def _(mo, pmap, theme):
    mo.iframe(pmap.html_page(theme), height=f"{pmap.height_px()}px")
    return


if __name__ == "__main__":
    app.run()
