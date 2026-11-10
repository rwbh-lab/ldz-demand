import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Model specification", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo
    import numpy as np

    from ldz_demand.charts import demand_model as dm
    from ldz_demand.charts import pages, style

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    DECISIONS = "https://github.com/rwbh-lab/ldz-demand/blob/main/docs/decisions.md"
    Q = pages.Q
    return DECISIONS, Q, dm, mo, np, pages


@app.cell(hide_code=True)
def _(DECISIONS, Q, mo, pages):
    pages.header("model_specification.py", mo.md(r"""
    # Model specification
    *How the model turns a day's weather into gas demand, one part at a time.*
    """), mo.md(rf"""
    **The official CWV's steps, refitted per LDZ to weather averaged over the LDZ: a day's weather becomes
    one number, the CWV, and demand {Q} is a straight line in it plus the calendar.**
    """ + r"""
    $$
    \begin{aligned}
    E_t &= y \cdot E_{t-1} + (1-y)\,T_t && \text{Memory}\\
    CW_t &= E_t - I_2 \max(0, W_t - W_0)\max(0, T_0 - T_t) && \text{Wind}\\
    &\quad + S_0\,SR_t && \text{Solar}\\
    &\quad + S_c\,g(\text{day}) && \text{Season}\\
    CWV_t &= f(CW_t;\ V_0, I_3, V_1, V_2, q) && \text{Bend}\\
    Q_t &= a + b\,CWV_t + \text{calendar}_t && \text{Demand}
    \end{aligned}
    $$
    """ + rf"""
    *T* is the gas day's temperature, weighted to the hours homes heat (*Temperature*); *W* the wind
    speed; *SR* solar radiation: all ERA5, averaged over the LDZ and weighted by where gas is used. The
    calendar is day of week, bank holidays and Christmas. Drawn with the final fit
    (`ldz_demand.models.fit`; [decisions C1–C9]({DECISIONS}#cwv-model)); the fitted values for every LDZ
    are on [model calibration](/model-calibration), the scores on [backtesting results](/backtesting-results).
    """), notation=True)
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
def _(DECISIONS, dm, frame, mo, pages):
    mo.vstack([
        mo.md(f"""{pages.heading("Temperature", "Heating hours count double and nights half: a 9% smaller error")}

    - A gas day runs 05:00 to 05:00. Rather than a flat average of its hours, the hours when homes heat
      count more: **06–09 and 16–22 double, 23–05 half**.
    - The largest single improvement after the seasonal term, and it survives the ensemble forecasts'
      3- and 6-hourly steps ([P5]({DECISIONS}#p5-gas-day-temperature-weighted-to-the-heating-hours)).
    - It is usually a little warmer than the flat mean: the coldest hours are at night, which now count
      for less.
    """),
        mo.accordion({"Weight of each hour (chart)": dm.heating_profile()}),
        dm.gas_day_temperature(frame),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(fit, ldz, mo, np, pages):
    y_slider = mo.ui.slider(0.05, 0.95, step=0.05, value=0.85, label="Try y", show_value=True)
    _half = np.log(0.5) / np.log(fit.params.y)
    mo.vstack([
        mo.md(f"""{pages.heading("Memory", f"In {ldz}, a cold snap's effect halves in about {_half:.1f} days")}

    - Buildings and habits respond to the last few days' weather, not just today's.
    - The effective temperature **E** carries yesterday's value forward with weight *y* and adds today's
      with 1 − *y*. Fitted, **y = {fit.params.y:.2f}**: today counts about {1 - fit.params.y:.0%}.
    - Move the slider to see a shorter or longer memory.
    """),
        y_slider,
    ], gap=0.5)
    return (y_slider,)


@app.cell(hide_code=True)
def _(dm, fit, frame, y_slider):
    dm.effective_temperature(frame, fit.params.y, y_slider.value)
    return


@app.cell(hide_code=True)
def _(dm, fit, ldz, mo, pages):
    _p = fit.params
    _chill = _p.I2 * max(0.0, 10 - _p.W0) * max(0.0, _p.T0 - 0)
    mo.vstack([
        mo.md(f"""{pages.heading("Wind", "Wind makes a cold day count colder, and more so the colder it is")}

    - Wind takes **I2 · (wind above W0) · (temperature below T0)** off the day: more heat lost from
      buildings.
    - Fitted for {ldz}: I2 = {_p.I2:.3f}, W0 = {_p.W0:.1f} m/s, T0 = {_p.T0:.1f} °C. On a 0 °C day with a
      10 m/s wind, that is {_chill:.1f} °C colder.
    - A W0 below zero means wind chill applies at any wind speed.
    """),
        dm.wind_chill(_p),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(DECISIONS, dm, fit, frame, mo, pages):
    mo.vstack([
        mo.md(f"""{pages.heading("Solar", "Sunshine cuts heating: without it the model is 26% worse")}

    - A sunny cold day needs less gas than a dull one at the same temperature. The term is
      **S0 · solar radiation** (S0 = {fit.params.S0:.4f} per W m⁻²).
    - Small in winter, when the sun is weak; worth a degree or two in summer, when heating is mostly off
      anyway ([P6]({DECISIONS}#p6-variables-temperature-wind-solar)).
    """),
        dm.solar(fit.params, frame),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(DECISIONS, dm, fit, fits, ldz, mo, pages):
    mo.vstack([
        mo.md(f"""{pages.heading("Season", "A January day counts colder than its weather, an August day warmer")}

    - Heating goes on in autumn and is left on into spring, whatever the exact temperature.
    - One **smooth shape through the year, shared by all 13 LDZs**; only its size is fitted per LDZ
      ({ldz}: Sc = {fit.params.Sc:.2f} °C). Sharing gives the shape thirteen times the data
      ([C2, C3]({DECISIONS}#c2-a-seasonal-shape-shared-by-all-ldzs)).
    - The official CWV uses a seasonal profile built from decades of weather, which isn't public.
      Grey lines: the other LDZs.
    """),
        dm.seasonal_shape(fits, ldz),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(dm, fit, frame, ldz, mo, pages):
    _p = fit.params
    mo.vstack([
        mo.md(f"""{pages.heading("Bend", f"Above {_p.V1:.0f} °C demand flattens; below {_p.V0:.0f} °C each degree counts "
                                        f"{1 + _p.I3:.1f} times")}

    - Demand doesn't keep falling as it warms: once heating is off, more warmth changes little. Above
      V1 = {_p.V1:.1f} °C the response flattens (slope q = {_p.q:.2f}); above V2 = {_p.V2:.1f} °C it stops.
    - In real cold, demand rises faster than the line: below V0 = {_p.V0:.1f} °C each degree counts
      1 + I3 = {1 + _p.I3:.2f} times.
    - The dashed line is the published curve for {ldz}. Not exactly comparable: the official CW blends in
      its seasonal profile, so its scale differs. The ticks along the bottom are this LDZ's days.
    """),
        dm.transform(_p, ldz, frame, fit),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(mo):
    bend_x = mo.ui.radio(options={"CW": "cw", "Gas-day temperature": "temperature"}, value="CW",
                         label="Plot demand against", inline=True)
    mo.vstack([
        mo.md(r"""
        **Why bend it?** Against CW, demand is a curve: flat in summer, steeper in the cold. The line is the
        model, the bend then the straight line, tracing that curve. Switch to the plain gas-day temperature
        to see the raw relationship before wind, sun and season are folded in: the same shape, with more
        scatter.
        """),
        bend_x,
    ], gap=0.5)
    return (bend_x,)


@app.cell(hide_code=True)
def _(bend_x, dm, fit, frame):
    dm.demand_before_bend(fit, frame, bend_x.value)
    return


@app.cell(hide_code=True)
def _(DECISIONS, Q, dm, fit, frame, ldz, mo, pages):
    _c = dict(zip(fit.columns, fit.coef))
    mo.vstack([
        mo.md(f"""{pages.heading("Demand", f"In {ldz}, each degree of CWV is worth {abs(_c['cwv']):.1f} GWh/day")}

    - With the bending done in the CWV, {Q} is a **straight line** in it.
    - On top, the calendar against an ordinary Monday: a Saturday {_c['sat']:+.1f} GWh/day, a bank holiday
      {_c['bank_holiday']:+.1f}, a day in the Christmas period (24 Dec – 1 Jan) {_c['christmas']:+.1f},
      when offices and much industry close ([C6]({DECISIONS}#c6-demand-linear-in-the-cwv-plus-calendar-terms)).
    """),
        dm.demand_line(fit, frame),
        dm.calendar_effects(fit),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer(definitions=True)
    return


if __name__ == "__main__":
    app.run()
