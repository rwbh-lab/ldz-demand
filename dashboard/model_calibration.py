import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Model calibration", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import demand_model as dm
    from ldz_demand.charts import pages, style

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    DECISIONS = "https://github.com/rwbh-lab/ldz-demand/blob/main/docs/decisions.md"
    Q = pages.Q
    return DECISIONS, Q, dm, mo, pages


@app.cell(hide_code=True)
def _(Q, mo, pages):
    pages.header("model_calibration.py", mo.md(r"""
    # Model calibration
    *How the model's parameters are fitted to five years of demand, and what they came out as.*
    """), mo.md(rf"""
    **All 13 LDZs are fitted together on five gas years of {Q}, with recent years counting more, by a
    loss that keeps a few odd days from dragging the fit.**

    - **Recency**: how the fit follows the way gas is used now.
    - **Parameters**: one LDZ's fitted values against the published ones.
    - **Alternatives**: what else was tried, and why it lost.

    The model's form is on [Model specification](/model-specification); how well it predicts days it
    wasn't fitted on, on [Backtesting results](/backtesting-results).
    """), notation=True)
    return


@app.cell(hide_code=True)
def _(DECISIONS, Q, mo):
    from ldz_demand.models import cwv
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
    # the LDZs whose cold-weather upturn strength I3 sits on its upper bound (decision C4)
    _i3 = cwv.NAMES.index("I3")
    at_cap = sorted(name for name, f in fits.items() if f.params.I3 >= cwv.bounds(name)[1][_i3] - 1e-3)
    ldz_picker = mo.ui.dropdown(options=sorted(fits), value="NT", label="LDZ")
    mo.vstack([
        mo.accordion({"How the fit works": mo.md(rf"""
        - **What it is fitted to:** each LDZ's {Q}, total demand minus daily-metered, per gas day: the
          demand the weather drives ([National Gas data](/ng-ldz-daily), Part II). The 18 months when
          South East's total was missing a feed are repaired for fitting.
        - **Inputs:** the LDZ weather built from ERA5: the heating-hours gas-day temperature, wind and
          solar ([LDZ weather](/ldz-weather)).
        - **How:** all thirteen LDZs together, because the seasonal shape is shared, by **robust least
          squares** (a soft-L1 loss: large errors count less than when squared, so a few odd days can't
          drag the fit). Each parameter is held within a physically sensible range.
        - **The cold-weather upturn** is capped at 0.4, or twice the published strength if that is more:
          five years have too few very cold days to pin it down. The fit reaches the cap in
          {len(at_cap)} LDZs ({", ".join(at_cap)}); lifting it changes the coldest days by under
          0.1 GWh/day ([C4]({DECISIONS}#c4-a-fitted-cold-weather-upturn-bounded)).
        - **Which days:** every usable day in the five gas years, recent years counting more (next).
        """)}),
        ldz_picker,
    ], gap=0.5)
    return at_cap, final, fits, frames, ldz_picker


@app.cell(hide_code=True)
def _(fits, frames, ldz_picker):
    ldz = ldz_picker.value
    fit, frame = fits[ldz], frames[ldz]
    return fit, frame, ldz


@app.cell(hide_code=True)
def _(DECISIONS, dm, final, fit, frame, mo, pages):
    _half = final.MODEL.half_life
    mo.vstack([
        mo.md(f"""{pages.heading("Recency", ("Each day's weight halves every year, " if _half == 1 else
                                            f"Each day's weight halves every {_half:g} years, ") +
                                           "so the model follows demand since the 2022 price shock")}

    - Demand fell after the 2022 price shock and has partly recovered since.
    - Rather than pick break dates, each training day is weighted by its age
      ([C7]({DECISIONS}#c7-follow-behaviour-by-weighting-recent-years)).
    - Below the weights, what that adjusts for: actual demand against today's model, month by month.
      Earlier years sit above zero, where demand was higher than now; recent months sit close to it.
    """),
        dm.recency(fit, frame, _half),
        dm.drift(fit, frame),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(at_cap, dm, fit, ldz, mo, pages):
    _capped = ldz in at_cap
    _statement = (f"{ldz}'s cold-weather upturn is on its cap, as in {len(at_cap)} of 13 LDZs" if _capped else
                  f"{ldz}'s fitted values against the published ones; its cold-weather upturn is inside its cap")
    mo.vstack([
        mo.md(f"""{pages.heading("Parameters", _statement)}

    - Ours against the published values for October 2025 onwards, in our units (wind in m/s).
    - The seasonal shape and solar have no published equivalent in these units.
    - The published values are fitted to station weather and the official seasonal profile, so they
      are a guide, not a target.
    """),
        mo.md(dm.markdown_table(dm.parameter_table(fit, ldz))),
        mo.md("And the line demand is fitted on ([Model specification](/model-specification), *Demand*):"),
        mo.md(dm.markdown_table(dm.linear_table(fit))),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(DECISIONS, mo, pages):
    mo.md(f"""{pages.heading("Alternatives", "Six tried; each scored worse, gained nothing net, or was held back")}

    Each was fitted and scored the same way; the reasons are in the [decisions]({DECISIONS}), the scores in
    the [results](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/results.md).

    - **No seasonal term**: 17% worse; a **slow "heating-season" temperature** instead of the shape:
      close behind (C2).
    - **The official form of the seasonal term**: no unique solution, so rewritten (C3).
    - **A straight line instead of the cold upturn**, or **the published upturn**: both worse on cold
      days (C4).
    - **A separate summer level**: better in July–August, worse in spring; no net gain (C5).
    - **Fixed coefficients**, **a break in autumn 2022**, **a level per gas year**: recency weighting
      beat them over three forward years (C7).
    - **The day's minimum / maximum temperature**: a small gain, held back because ERA5 and the
      ensemble define them differently (N2).
    """)
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer(definitions=True)
    return


if __name__ == "__main__":
    app.run()
