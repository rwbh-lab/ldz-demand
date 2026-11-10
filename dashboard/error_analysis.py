import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · Error analysis", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo
    import numpy as np

    from ldz_demand.charts import errors as ech
    from ldz_demand.charts import forecasts as fch
    from ldz_demand.charts import pages, style
    from ldz_demand.models import forecast as fcm
    from ldz_demand.models import verification as ver

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    P_RANGE, Q, Q6 = pages.P_RANGE, pages.Q, pages.Q_at(6)
    return P_RANGE, Q, Q6, ech, fch, fcm, mo, np, pages, ver


@app.cell(hide_code=True)
def _(P_RANGE, Q6, mo, pages):
    pages.header("error_analysis.py", mo.md(r"""
    # Error analysis
    *Whether the forecasts' ranges are the right width, and where the errors come from.*
    """), mo.md(rf"""
    **A {P_RANGE} range should hold demand on 8 days in 10. Scored so far on a few autumn weeks, the
    published range holds more than that at longer lead times, and the weather forecast behind it is too
    narrow on the first days. It takes a winter to be sure.**

    - **Coverage**: how often closed-out demand {Q6} lands inside the range, and a test of it.
    - **Bias**: whether the median runs high or low.
    - **Tails**: where demand lands among all the percentiles, not just {P_RANGE}.
    - **Weather alone**: where the weather that happened lands among the 50 members, without the
      demand model.

    Only closed-out (D+6) days are scored. The ranges combine the members' weather with the model's own
    errors ([live forecasts](/live-forecasts), *How the ranges are built*), so the two are scored apart:
    the published range against demand, and the members against ERA5's weather.
    """), notation=True)
    return


@app.cell(hide_code=True)
def _(fch, fcm, mo):
    with mo.status.spinner(title="Loading forecasts and published demand"):
        runs = fch.wide(fcm.load_runs())
        mo.stop(runs.empty, mo.callout(mo.md("**No forecasts yet.** Run `python -m ldz_demand.models.forecast`."),
                                        kind="warn"))
        actual = fcm.actuals(since=runs["run_date"].min())
    ldz_picker = mo.ui.dropdown(options=["GB", *sorted(set(runs["ldz"]) - {"GB"})], value="GB", label="LDZ")
    ldz_picker
    return actual, ldz_picker, runs


@app.cell(hide_code=True)
def _(actual, fch, ldz_picker, mo, runs):
    ldz = ldz_picker.value
    _v = fch.verification(runs, actual, ldz)
    scored = _v[~_v["provisional"]] if not _v.empty else _v
    mo.stop(scored.empty, mo.callout(mo.md(
        "*No forecast day is closed out yet: demand closes out six days after the gas day, so a run is first "
        "scored a week after it.*"), kind="info"))
    return ldz, scored


@app.cell(hide_code=True)
def _(P_RANGE, ech, ldz, mo, np, pages, scored, ver):
    test = ver.coverage_test(scored["in 10–90%"], scored["gas_day"])
    _wx = ver.coverage_test(scored["in weather-only 10–90%"], scored["gas_day"])
    lead0 = ver.exact_test(scored.loc[scored["lead_days"] == 0, "in 10–90%"])
    _by_lead = ver.coverage_by_lead(scored)
    _pct = lambda x: f"{x:.0%}"  # noqa: E731
    _pval = lambda p: "below 0.001" if p < 0.001 else f"{p:.3f}"  # noqa: E731
    if test["p_cluster"] < 0.05:
        _verdict = "too wide" if test["share"] > 0.8 else "too narrow"
    else:
        _verdict = "no clear difference yet"
    _day0 = (f"; on the day itself, {_pct(lead0['share'])}" if lead0["n"] else "")
    _statement = f"{_pct(test['share'])} of days inside {P_RANGE}, against 80%: {_verdict}{_day0}"
    _bands = ver.coverage_by_band(scored)
    mo.vstack([
        mo.md(pages.heading("Coverage", _statement)),
        mo.Html(pages.tiles([
            ("Published range", _pct(test["share"]), f"{test['inside']} of {test['n']} run–day pairs"),
            ("Weather only", _pct(_wx["share"]), "the members alone"),
            ("Lead day 0", _pct(lead0["share"]) if lead0["n"] else "–", f"{lead0['inside']} of {lead0['n']} days"),
            ("Gas days scored", f"{scored['gas_day'].nunique()}",
             f"{scored['gas_day'].min():%d %b} – {scored['gas_day'].max():%d %b}"),
        ])),
        mo.md(f"""
    - Each gas day is scored by every run that forecast it, up to 14, against the same actual: the
      {test['n']} pairs are worth about {test['n'] / test['design_effect']:.0f} independent ones, and fewer still
      while the days come from one spell of weather.
    - By lead time: {", ".join(f"days {r['lead days']} {_pct(r['blend'])} ({_pct(r['weather only'])} weather only)" for _, r in _bands.iterrows())}.
    """),
        ech.coverage_by_lead(_by_lead, f"{ldz}: share inside {P_RANGE} by lead day, with 95% intervals"),
        mo.accordion({"The test, step by step": mo.md(rf"""
        Each scored pair is inside the range or not. If the range is right, the chance it is inside is 0.8.

        1. **Hypotheses.** H₀: *p* = 0.80; H₁: *p* ≠ 0.80 (too wide and too narrow are both wrong).
        2. **Data.** {test['inside']} of *n* = {test['n']} pairs inside: *p̂* = {test['share']:.3f}.
        3. **Naive test**, as if every pair were independent. SE under H₀ = √(0.8 × 0.2 / {test['n']}) =
           {test['se_naive']:.4f}; *z* = ({test['share']:.3f} − 0.800) / {test['se_naive']:.4f} = **{test['z']:.2f}**;
           exact binomial *p* {_pval(test['p_naive'])}.
        4. **Why that overstates it.** The pairs cover only {test['clusters']} gas days, each scored by up to
           14 runs against one actual: one surprising day is several misses at once.
        5. **Cluster-robust test**, with the gas day as the unit: SE = √(G/(G−1) · Σ(kᵢ − *p̂* nᵢ)²) / *n*
           = {test['se_cluster']:.4f} (G = {test['clusters']}); *t* = **{test['t']:.2f}** on {test['dof']} degrees of
           freedom, *p* {_pval(test['p_cluster'])}; 95% interval {test['lo']:.0%} to {min(test['hi'], 1):.0%}. The design
           effect, {test['design_effect']:.1f}, makes the {test['n']} pairs worth about {test['n'] / test['design_effect']:.0f} independent ones.
        6. **One forecast per day**, lead day 0 alone: {lead0['inside']} of {lead0['n']} = {lead0['share']:.0%}; exact
           *p* {_pval(lead0['p']) if lead0['n'] else '–'}, 95% interval {lead0['lo']:.0%} to {lead0['hi']:.0%}.
        7. **Caveat.** Clustering by day doesn't remove the rest of the dependence: neighbouring days share
           the weather, so the true number of independent days is smaller and these *p*-values are optimistic.
           Telling 80% from 90% at one lead time (5% two-sided, 80% power) needs about
           ((1.96·√0.16 + 0.84·√0.09) / 0.1)² ≈ {np.ceil(((1.96 * 0.4 + 0.84 * 0.3) / 0.1) ** 2):.0f} independent days: about a winter.
        """), "By lead band (table)": pages.md(
            "| Lead days | Pairs | Gas days | Published range | Weather only |\n|---|---:|---:|---:|---:|\n" +
            "\n".join(f"| {r['lead days']} | {r['pairs']} | {r['gas days']} | {r['blend']:.0%} | {r['weather only']:.0%} |"
                      for _, r in _bands.iterrows()))}),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(ech, ldz, mo, pages, scored, ver):
    _bias = ver.bias_by_lead(scored)
    _all = scored["error %"].mean()
    _short = scored.loc[scored["lead_days"] <= 3, "error %"].mean()
    _word = lambda x: "high" if x > 0 else "low"  # noqa: E731
    mo.vstack([
        mo.md(f"""{pages.heading("Bias", f"The median runs {abs(_all):.1f}% {_word(_all)} on average; "
                                         f"{abs(_short):.1f}% {_word(_short)} on lead days 0–3")}

    - The ranges are centred on the model: the model errors added to the members widen the range but don't
      move it (no bias correction yet).
    - A bias that holds over a winter is worth correcting; over a few weeks it may be the season. The
      model is weakest in the shoulder months ([backtesting results](/backtesting-results), *By month*).
    """),
        ech.bias_by_lead(_bias, f"{ldz}: the median's mean error by lead day"),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(ech, ldz, mo, pages, scored, ver):
    _p = ver.pit(scored)
    _outside = _p["observed"].iloc[[0, -1]].sum()
    _middle = _p.loc[_p["band"].isin(["P25–P50", "P50–P75"]), "observed"].sum()
    mo.vstack([
        mo.md(f"""{pages.heading("Tails", f"{_outside:.0%} of days outside P05–P95, against 10%; "
                                          f"{_middle:.0%} in the middle half, against 50%")}

    - Each bar is the share of days whose actual fell in that band of the forecast. A calibrated forecast
      matches the short lines: bars that rise in the middle mean the range is too wide, bars that rise at
      the ends too narrow, and a lean to one side a bias.
    - {pages.P_RANGE} coverage alone can't test the extremes; this does, as far as a few weeks can.
    """),
        ech.pit(_p, f"{ldz}: where the actual fell among the forecast's percentiles"),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(mo, runs, ver):
    from ldz_demand.models import fit as _final

    with mo.status.spinner(title="Running each member's weather through the model (about 25 s for each run "
                                 "not yet cached)"):
        _fits, _inputs = _final.load(), _final.cached_model_inputs()
        members = ver.cached_member_weather(runs["run_date"].unique(), _fits, _inputs)
        era5 = ver.era5_weather(_fits, _inputs)
    weather_var = mo.ui.radio(options={"Temperature": "t2m", "CWV": "cwv"}, value="Temperature", label="Weather",
                              inline=True)
    lead_band = mo.ui.dropdown(options={"All lead days": "all", **{f"Lead days {a}–{b}": f"{a}-{b}"
                                                                   for a, b in ver.LEAD_BANDS}},
                               value="All lead days", label="Lead days")
    return era5, lead_band, members, weather_var


@app.cell(hide_code=True)
def _(ech, era5, lead_band, ldz, members, mo, np, pages, ver, weather_var):
    mo.stop(members.empty, mo.md("*No member weather yet (runs from 13 Oct 2026 carry solar, which the model needs).*"))
    _pooled = ldz == "GB"
    _m = members if _pooled else members[members["ldz"] == ldz]
    _r = ver.ranks(_m, era5, weather_var.value)
    mo.stop(_r.empty, mo.md("*No ERA5 yet for the days these runs forecast (ERA5 is six days behind).*"))
    _unit = "°C"
    _name = "temperature" if weather_var.value == "t2m" else "CWV"
    _ss = ver.spread_skill(_r)
    _ratio = lambda a, b: float(np.mean(_ss.loc[_ss["lead_days"].between(a, b), "ratio"]))  # noqa: E731
    _word = lambda x: "too narrow" if x < 0.85 else "too wide" if x > 1.15 else "about right"  # noqa: E731
    _early, _mid, _late = _ratio(0, 1), _ratio(2, 9), _ratio(10, 13)
    _bias = float((_r["mean"] - _r["era5"]).mean())
    _statement = (f"{_word(_early).capitalize()} at first, {_word(_late)} after day 9; "
                  f"{abs(_bias):.1f} °C {'cold' if _bias < 0 else 'warm'} on average")
    _band = _r if lead_band.value == "all" else _r[_r["lead_days"].between(*map(int, lead_band.value.split("-")))]
    _h = ver.rank_histogram(_band)
    _chi = ver.chi2_flat(_h)
    _where = "all 13 LDZs pooled" if _pooled else ldz
    mo.vstack([
        mo.md(f"""{pages.heading("Weather alone", _statement)}

    - The weather that happened (ERA5) placed among each run's 50 members, gas day by gas day: this tests
      the weather forecast on its own, without the demand model or its errors. Shown for the heating-hours
      temperature, or the CWV the model makes of it.
    - **Spread against error:** for a well-calibrated ensemble, the members' spread matches the error of
      their mean. Here the ratio is {_early:.1f} on lead days 0–1, {_mid:.1f} on days 2–9 and {_late:.1f} on days
      10–13 (1 is right; for the {_name}, {_where}).
    - This is why the published range is too wide late: by then the members' spread already covers the
      weather, and the model's errors are added on top at full size.
    """),
        mo.hstack([weather_var, lead_band], justify="start", gap=2),
        ech.rank_histogram(_h, f"Where ERA5's {_name} fell among the members · {_where}"),
        mo.md(f"*{_chi['n']:,} run–LDZ–day cases; against a flat histogram, χ² = {_chi['chi2']:.0f} on {_chi['dof']} "
              "degrees of freedom. The LDZs and runs share their weather, so the cases are far from independent: "
              "read the shape, not the test.*"),
        ech.spread_skill(_ss, f"Members' spread against the error of their mean · {_name}, {_where}", _unit),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(mo, pages, scored):
    _shown = scored.assign(
        run_date=scored["run_date"].dt.strftime("%d %b"), gas_day=scored["gas_day"].dt.strftime("%a %d %b"),
        **{"error %": scored["error %"].round(1)},
        **{c: scored[c].round(0) for c in ("actual", "p50", "p10", "p90")})[
        ["run_date", "gas_day", "lead_days", "actual", "p50", "p10", "p90", "error %", "in 10–90%",
         "in weather-only 10–90%"]]
    mo.vstack([
        mo.md(f"""{pages.heading("Still to come", "A winter of scores, then a calibration per lead day")}

    - **A winter.** The scores so far cover a few autumn weeks; cold spells, where the tails matter, are
      still to come.
    - **Calibration per lead day**, if a winter confirms the pattern: scale the members' spread and the
      model's errors by lead day, fitted on closed-out days (the usual post-processing of an ensemble).
    - **The members' cold lean**, if it lasts: a fixed correction to the ensemble temperature before the
      model.
    """),
        mo.accordion({"Every scored forecast day (table)": mo.ui.table(
            _shown, selection=None, show_column_summaries=False, page_size=15)}),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer(definitions=True)
    return


if __name__ == "__main__":
    app.run()
