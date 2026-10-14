import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Demand model", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import demand_model as dm
    from ldz_demand.charts import style

    theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return dm, mo


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages

    _pages.nav("demand_model.py")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Demand model
    *How the model turns a day's weather into gas demand, one part at a time.*

    The model has two stages. First, a day's weather becomes one number — the **Composite Weather
    Variable (CWV)**, roughly "how cold the day feels to gas demand", in °C. Then demand is a straight line
    in the CWV, plus calendar effects. The CWV is built in the same steps as the official one; every
    parameter is refitted to our weather, per LDZ.

    $$
    \begin{aligned}
    E_t &= y \cdot E_{t-1} + (1-y)\,T_t && \text{§2}\\
    CW_t &= E_t - I_2 \max(0, W_t - W_0)\max(0, T_0 - T_t) + S_0\,SR_t + S_c\,g(\text{day}) && \text{§3–5}\\
    CWV_t &= f(CW_t;\ V_0, I_3, V_1, V_2, q) && \text{§6}\\
    \text{demand}_t &= a + b\,CWV_t + \text{calendar}_t && \text{§7–8}
    \end{aligned}
    $$

    *T* is the gas day's temperature (§1), *W* the wind speed, *SR* solar radiation — all ERA5, averaged
    over the LDZ and weighted by where gas is used. The calendar is day of week, bank holidays and
    Christmas; recent years count more in the fit (§8). This page shows what each part does, with the
    **final fit** (`ldz_demand.models.fit`; `docs/decisions.md` C1 – C9). How well the model scores, and
    why each part was chosen over the alternatives, is in `docs/results.md`.
    """)
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
            f"demand tables (`docs/user_guide.md`).\n\nError: `{load_error}`"), kind="warn"),
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
def _(dm, frame, mo):
    mo.vstack([
        mo.md(r"""
        ## 1 · The gas day's temperature

        A gas day runs 05:00 to 05:00. Rather than a flat average of its hours, the model weights the
        hours when homes heat: **06–09 and 16–22 count double, 23–05 half**. Night-time temperature
        matters less to demand than the temperature while people are up. It is the largest single
        improvement after the seasonal term (−9% error), and it survives the ensemble forecasts' 3- and
        6-hourly steps (`decisions.md` P5).
        """),
        dm.heating_profile(),
        dm.gas_day_temperature(frame),
        mo.md("*The heating-hours temperature is usually a little warmer than the flat mean — the coldest "
              "hours are at night, which now count for less.*"),
    ])
    return


@app.cell(hide_code=True)
def _(fit, mo, np):
    y_slider = mo.ui.slider(0.05, 0.95, step=0.05, value=0.85, label="Try y", show_value=True)
    mo.vstack([
        mo.md(rf"""
        ## 2 · Effective temperature: the model's memory

        Buildings and habits respond to the weather of the last few days, not just today's.
        **E** carries yesterday's value forward with weight *y* and adds today's temperature with weight
        1 − *y*. Fitted here, **y = {fit.params.y:.2f}**: today counts about {1 - fit.params.y:.0%}, and a
        cold snap's effect halves in about {np.log(0.5) / np.log(fit.params.y):.1f} days. Move the slider to
        see a shorter or longer memory.
        """),
        y_slider,
    ])
    return (y_slider,)


@app.cell(hide_code=True)
def _(dm, fit, frame, y_slider):
    dm.effective_temperature(frame, fit.params.y, y_slider.value)
    return


@app.cell(hide_code=True)
def _(dm, fit, mo):
    _p = fit.params
    mo.vstack([
        mo.md(rf"""
        ## 3 · Wind chill

        Wind makes a cold day count as colder — more heat lost from buildings. The reduction is
        **I2 · (wind above W0) · (temperature below T0)**: it grows with wind, and the colder the day,
        the more the wind matters. Fitted: I2 = {_p.I2:.3f}, W0 = {_p.W0:.1f} m/s, T0 = {_p.T0:.1f} °C.
        A W0 below zero means wind chill applies at any wind speed.
        """),
        dm.wind_chill(_p),
    ])
    return


@app.cell(hide_code=True)
def _(dm, fit, frame, mo):
    mo.vstack([
        mo.md(rf"""
        ## 4 · Solar

        Sunshine warms buildings and cuts heating — a sunny cold day needs less gas than a dull one at
        the same temperature. The term is **S0 · solar radiation**, added to CW (S0 = {fit.params.S0:.4f}
        per W m⁻²). Small in winter, when the sun is weak; worth a degree or two of CW in summer, when
        heating is mostly off anyway. Without it the model is 26% worse (`decisions.md` P6).
        """),
        dm.solar(fit.params, frame),
    ])
    return


@app.cell(hide_code=True)
def _(dm, fit, fits, ldz, mo):
    mo.vstack([
        mo.md(rf"""
        ## 5 · The seasonal shape

        Demand isn't only weather: heating goes on in autumn and is left on into spring, regardless of
        the exact temperature. The official CWV handles this with a seasonal profile built from decades
        of weather, which isn't public. Here it is a **smooth shape through the year, shared by all 13
        LDZs**, with only its size fitted per LDZ ({ldz}: Sc = {fit.params.Sc:.2f} °C). Sharing it gives
        the shape thirteen times the data (`decisions.md` C2, C3).

        Negative in winter: a January day counts as colder than its weather alone, an August day as
        warmer. Grey lines: the other LDZs.
        """),
        dm.seasonal_shape(fits, ldz),
    ])
    return


@app.cell(hide_code=True)
def _(dm, fit, frame, ldz, mo):
    _p = fit.params
    mo.vstack([
        mo.md(rf"""
        ## 6 · From CW to CWV: summer cut-off and cold upturn

        Demand doesn't fall forever as it warms — once heating is off, more warmth changes little. And
        in real cold, demand rises faster than the line. So CW is bent before demand sees it:

        - **Summer:** above V1 = {_p.V1:.1f} °C the response flattens (slope q = {_p.q:.2f}), and above
          V2 = {_p.V2:.1f} °C it stops.
        - **Cold:** below V0 = {_p.V0:.1f} °C each degree counts 1 + I3 = {1 + _p.I3:.2f} times.

        The dashed line is the published curve. It isn't exactly comparable: the official CW blends in
        their seasonal profile, so its scale differs from ours. The ticks along the bottom are this
        LDZ's days.
        """),
        dm.transform(_p, ldz, frame, fit),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    bend_x = mo.ui.radio(options={"CW": "cw", "Gas-day temperature": "temperature"}, value="CW",
                         label="Plot demand against", inline=True)
    mo.vstack([
        mo.md(r"""
        **Why bend it? Look at demand before the bend.** Against CW, demand is a curve: it flattens as
        heating switches off in summer, and steepens in the cold. The line is the model — §6's bend
        followed by §7's straight line — tracing that curve. After the bend (§7) the same days lie on a
        straight line. Switch to the plain gas-day temperature to see the raw relationship, before wind,
        sun and season are folded in: the same shape, with more scatter.
        """),
        bend_x,
    ])
    return (bend_x,)


@app.cell(hide_code=True)
def _(bend_x, dm, fit, frame):
    dm.demand_before_bend(fit, frame, bend_x.value)
    return


@app.cell(hide_code=True)
def _(dm, fit, frame, mo):
    _c = dict(zip(fit.columns, fit.coef))
    mo.vstack([
        mo.md(rf"""
        ## 7 · Demand from the CWV

        With the bending done in the CWV, demand is a **straight line**: each degree of CWV is worth
        {abs(_c["cwv"]):.1f} GWh/day here. On top of it, the calendar: weekends, bank holidays and the
        Christmas period (24 Dec – 1 Jan) — offices and much industry close, beyond the bank holidays
        themselves (`decisions.md` C6).
        """),
        dm.demand_line(fit, frame),
        dm.calendar_effects(fit),
    ])
    return


@app.cell(hide_code=True)
def _(dm, final, fit, frame, mo):
    mo.vstack([
        mo.md(rf"""
        ## 8 · Following behaviour: recent years count more

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
        ## 9 · All parameters for {ldz}

        Ours against the published values for October 2025 onwards, in our units (wind in m/s). The
        seasonal shape and solar have no published equivalent in these units.
        """),
        mo.md(dm.markdown_table(dm.parameter_table(fit, ldz))),
        mo.md("And the line demand is fitted on (§7):"),
        mo.md(dm.markdown_table(dm.linear_table(fit))),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 10 · Alternatives tried

    Each was fitted and scored the same way; the reasons are in `docs/decisions.md`, the scores in
    `docs/results.md`.

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

    *Interactivity here is kept light — an LDZ picker and one slider. More could be added (for example
    sliders on the CW → CWV curve).*
    """)
    return


@app.cell(hide_code=True)
def _():
    import numpy as np

    return (np,)


if __name__ == "__main__":
    app.run()
