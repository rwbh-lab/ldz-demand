import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Model calibration", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import demand_model as dm
    from ldz_demand.charts import style

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return dm, mo


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.charts import pages as _pages

    _pages.header("model_calibration.py", mo.md(r"""
    # Model calibration
    *How the model's parameters are fitted to five years of demand, and what they came out as.*
    """), mo.md(r"""
    The [Model specification](/model-specification) sets out the model's form; here it meets the data.

    - **What it is fitted to:** each LDZ's total demand minus its daily-metered demand, per gas day — the
      demand the weather drives ([National Gas data](/ng-ldz-daily), Part II). The 18 months when South
      East's total was missing a feed are repaired for fitting.
    - **Inputs:** the LDZ weather built from ERA5 — the heating-hours gas-day temperature, wind and
      solar ([LDZ weather](/ldz-weather)).
    - **How:** all thirteen LDZs are fitted together, because the seasonal shape is shared, by **robust
      least squares** (a soft-L1 loss: large errors count less than when squared, so a few odd days
      can't drag the fit). Each parameter is held within a physically sensible range; the cold-weather
      upturn is held near the published values, as five years have few cold days.
    - **Which days:** every usable day in the five gas years, with recent years counting more (§1).

    How well the fitted model predicts days it wasn't fitted on is on [Backtesting results](/backtesting-results).
    """))
    return


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.models import fit as final

    with mo.status.spinner(title="Loading the model inputs (about a minute the first time, then cached for a day)"):
        try:
            fits = final.load()
            frames = final.cached_model_inputs()
            load_error = None
        except Exception as exc:  # show setup help instead of a traceback
            fits, frames, load_error = None, None, exc
    mo.stop(
        load_error is not None,
        mo.callout(mo.md(
            "**Couldn't load the model or its inputs.** The page needs the fitted model "
            "(`src/ldz_demand/models/data/final_fit.csv`, `python -m ldz_demand.models.fit`) and the weather and "
            f"demand tables (the [user guide](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_guide.md)).\n\nError: `{load_error}`"), kind="warn"),
    )
    ldz_picker = mo.ui.dropdown(options=sorted(fits), value="NT", label="LDZ")
    ldz_picker
    return final, fits, frames, ldz_picker


@app.cell(hide_code=True)
def _(fits, frames, ldz_picker):
    ldz = ldz_picker.value
    fit, frame = fits[ldz], frames[ldz]
    return fit, frame, ldz


@app.cell(hide_code=True)
def _(dm, final, fit, frame, mo):
    mo.vstack([
        mo.md(rf"""
        ## 1 · Following behaviour: recent years count more

        Demand fell after the 2022 price shock and has partly recovered since. Rather than pick break
        dates, each training day is **weighted by its age, halving every {final.MODEL.half_life:g} year**,
        so the model follows how people use gas now (`decisions.md` C7).
        """),
        dm.recency(fit, frame, final.MODEL.half_life),
        mo.md("What that adjusts for: the gap between actual demand and today's model, month by month. "
              "Earlier years sit above zero where demand was higher than now; recent months sit close to it."),
        dm.drift(fit, frame),
    ])
    return


@app.cell(hide_code=True)
def _(dm, fit, ldz, mo):
    mo.vstack([
        mo.md(rf"""
        ## 2 · All parameters for {ldz}

        Ours against the published values for October 2025 onwards, in our units (wind in m/s). The
        seasonal shape and solar have no published equivalent in these units.
        """),
        mo.md(dm.markdown_table(dm.parameter_table(fit, ldz))),
        mo.md("And the line demand is fitted on ([Model specification](/model-specification), §7):"),
        mo.md(dm.markdown_table(dm.linear_table(fit))),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3 · Alternatives tried

    Each was fitted and scored the same way; the reasons are in the [decisions](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/decisions.md), the scores in
    the [results](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/results.md).

    - **No seasonal term** — 17% worse; a **slow "heating-season" temperature** instead of the shape —
      close behind (C2).
    - **The official form of the seasonal term** — no unique solution, so rewritten (C3).
    - **A straight line instead of the cold upturn**, or **the published upturn** — both worse on cold days (C4).
    - **A separate summer level** — better in July – August, worse in spring; no net gain (C5).
    - **Fixed coefficients**, **a break in autumn 2022**, **a level per gas year** — recency weighting
      beat them over three forward years (C7).
    - **The day's minimum / maximum temperature** — a small gain, held back because ERA5 and the
      ensemble define them differently (N2).

    ---

    *Interactivity here is kept light — an LDZ picker. More could be added (for example sliders on the
    CW → CWV curve on the specification page).*
    """)
    return


if __name__ == "__main__":
    app.run()
