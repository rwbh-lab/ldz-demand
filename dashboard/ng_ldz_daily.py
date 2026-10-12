import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · National Gas data", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import ng_ldz_daily as ng
    from ldz_demand.charts import style
    from ldz_demand.data import ldz_energy as le

    theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return le, mo, ng


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages

    _pages.nav("ng_ldz_daily.py")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # National Gas LDZ data

    Daily gas demand for each of GB's 13 Local Distribution Zones (LDZs), as published by National Gas.
    This page checks the raw data before any modelling: **what is there, whether it adds up, and how
    demand responds to weather.**

    The model's target is **total demand minus daily-metered (DM) demand** — the weather-sensitive
    part, built from metered quantities rather than the published NDM allocation (which is itself
    calculated from the official weather variable, so fitting to it would be circular).
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.config import create_config
    from ldz_demand.data.datasets import NG_LDZ_DAILY, NG_OFFTAKE_DAILY
    from ldz_demand.data.store import get_store

    try:
        _store = get_store(create_config())
        raw = _store.read(NG_LDZ_DAILY)
        offtakes = _store.read(NG_OFFTAKE_DAILY)
        load_error = None
    except Exception as exc:  # show setup help instead of a traceback
        raw, offtakes, load_error = None, None, exc

    mo.stop(
        raw is None or raw.empty,
        mo.callout(mo.md(
            "**No National Gas data found.** Build it first — see `docs/user_guide.md` §5.1:\n\n"
            "```bash\npython -m ldz_demand.data.ingest.national_gas refresh\n"
            "python -m ldz_demand.data.build.ng_ldz_daily\n"
            "python -m ldz_demand.data.build.ng_offtake_daily\n```"
            + (f"\n\nError: `{load_error}`" if load_error else "")
        ), kind="warn"),
    )
    has_offtakes = offtakes is not None and not offtakes.empty
    return has_offtakes, offtakes, raw


@app.cell(hide_code=True)
def _(has_offtakes, le, mo, offtakes, raw):
    energy = le.energy_frame(raw, offtakes if has_offtakes else None)
    _ldz = energy.drop(index=le.GB, level="ldz")
    _flags = _ldz["flag"].value_counts()
    _days = raw["gas_day"]
    _bad = int((_ldz["flag"] != "ok").sum())

    mo.vstack([
        mo.hstack([
            mo.stat(f"{(_days.max() - _days.min()).days / 365.25:.1f} years", label="History",
                    caption=f"{_days.min():%d %b %Y} → {_days.max():%d %b %Y}"),
            mo.stat(f"{raw['ldz'].nunique()} LDZs", label="Zones", caption=f"{raw['item'].nunique()} items each"),
            mo.stat(f"{raw['value'].notna().sum():,}", label="Values",
                    caption="ng_ldz_daily" + (f" + {offtakes['value'].notna().sum():,} offtake" if has_offtakes else "")),
            mo.stat(f"{_bad}", label="Flagged LDZ-days",
                    caption=" · ".join(f"{_flags.get(f, 0)} {f.replace('_', ' ')}" for f in le.FLAGS[1:] if _flags.get(f, 0))),
        ], widths="equal", gap=1),
        mo.md("") if has_offtakes else mo.callout(mo.md(
            "Offtake data not loaded, so the offtake checks (§3b) are off and the simpler ratio rule is used. "
            "Run `python -m ldz_demand.data.ingest.national_gas refresh --series offtakes` then "
            "`python -m ldz_demand.data.build.ng_offtake_daily`."), kind="info"),
    ])
    return (energy,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1 · Coverage

    Every core series is complete from October 2021. Two things stand out: **unidentified gas (UIG)
    is only published from March 2025**, and the most recent ~6 days have no **D+6** (closed-out)
    values yet — they arrive a week behind the provisional D+1 figures.
    """)
    return


@app.cell(hide_code=True)
def _(ng, raw):
    ng.coverage(raw)
    return


@app.cell(hide_code=True)
def _(le, mo):
    ldz_picker = mo.ui.dropdown(options=[le.GB, *le.LDZS], value=le.GB, label="Zone (§2–3)")
    mo.vstack([
        mo.md(r"""
        ## 2 · What demand is made of

        Total demand is metered as gas enters each LDZ. It splits into **daily-metered** sites (large
        industry and business — fairly flat) and **non-daily-metered** demand (homes and small business —
        strongly seasonal). Total demand is published as a volume (mcm), so it is converted to energy with
        each day's calorific value; everything below is GWh/day.

        The thin line is the published total; the space between it and the stacked parts is gas the parts
        don't account for (§3). Click *NTS offtakes* in the legend to compare with the metered gas entering
        from the national transmission system (§3b). This zone picker drives §2 and §3; §3b and §4 have
        their own, since they work per LDZ.
        """),
        ldz_picker,
    ])
    return (ldz_picker,)


@app.cell(hide_code=True)
def _(energy, ldz_picker, ng):
    ng.composition(energy, ldz_picker.value)
    return


@app.cell(hide_code=True)
def _(mo):
    gap_units = mo.ui.radio(options={"GWh / day": False, "% of total": True}, value="GWh / day",
                            label="Units", inline=True)
    mo.vstack([
        mo.md(r"""
        ## 3 · Do the parts add up?

        **Total − DM − NDM** is what the published parts don't explain: unidentified gas plus LDZ
        shrinkage (leakage and own use). Once UIG is published (March 2025) we can subtract it too,
        leaving **shrinkage alone** — a fairly steady ~0.6–1 GWh/day per LDZ, so ~0.3% of winter
        demand but ~1.5% in summer. Flagged days (✕, see §3b) are excluded.
        """),
        gap_units,
    ])
    return (gap_units,)


@app.cell(hide_code=True)
def _(energy, gap_units, ldz_picker, ng):
    ng.gap(energy, ldz_picker.value, as_pct=gap_units.value)
    return


@app.cell(hide_code=True)
def _(has_offtakes, mo):
    mo.md(r"""
    ## 3b · Checking totals against NTS offtakes

    National Gas also publishes the energy taken from the national transmission system (NTS) at each
    of the 122 LDZ offtake points — an independent meter of gas entering each LDZ. In most LDZs the
    offtakes account for almost all of the total. **SE is different: it normally takes a steady
    ~31 GWh/day from a non-NTS input** (about a quarter of its demand).

    From **September 2022 to February 2024 that input vanishes from SE's published total** — the total
    equals the offtakes alone — and then returns. Nothing else moves to compensate: the gas is simply
    missing from the published figure. Because the missing input is so steady, those days can be
    **repaired** (offtakes + the usual input, uncertainty ~±5 GWh/day) or **excluded**; the model is
    fitted both ways (§4) to check the result doesn't depend on the choice.
    """ if has_offtakes else r"""
    ## 3b · Checking totals against NTS offtakes

    *Needs the offtake data — see the note at the top of the page.*
    """)
    return


@app.cell(hide_code=True)
def _(energy, has_offtakes, le, mo, ng):
    feed_picker = mo.ui.dropdown(options=list(le.LDZS), value="SE", label="LDZ")
    mo.vstack([
        ng.offtake_share(energy),
        mo.md("Each LDZ's offtakes cover ~94–103% of its total on a typical day — except **SE (~70%)**, "
              "whose non-NTS input makes up the rest. Pick an LDZ to see its day-by-day check:"),
        feed_picker,
    ]) if has_offtakes else None
    return (feed_picker,)


@app.cell(hide_code=True)
def _(energy, feed_picker, has_offtakes, ng):
    ng.feed_check(energy, feed_picker.value) if has_offtakes else None
    return


@app.cell(hide_code=True)
def _(energy, le, mo):
    _flagged = le.flagged_days(energy)
    mo.accordion({
        f"Flagged LDZ-days ({len(_flagged)}) — table": mo.ui.table(_flagged, page_size=12, selection=None),
        "How this was computed": mo.md(rf"""
        - Energy: `total_GWh = total_mcm × CV / 3.6`; DM, NDM, UIG and offtakes are published in kWh (÷ 10⁶).
        - `ratio = total / (DM + NDM)`; **invalid** if < {le.INVALID_BELOW}.
        - `other = total − Σ NTS offtakes`; `usual` = that LDZ's median.
          **missing feed** if usual > {le.FEED_MATERIAL:g} GWh/day and other < {le.FEED_MISSING_SHARE:g} × usual
          (repaired total = offtakes + usual); **mismatch** if |other − usual| > max({le.MISMATCH_ABS:g} GWh, {le.MISMATCH_REL:.0%} of total).
        - Without offtake data: **suspect** if ratio < {le.SUSPECT_BELOW}.
        - GB = sum of the 13 LDZs; a GB day takes the worst flag of its LDZs.
        - Code: `ldz_demand.data.ldz_energy` (data), `ldz_demand.charts.ng_ldz_daily` (charts) · data: `docs/user_guide.md` §4.1.
        """),
    })
    return


@app.cell(hide_code=True)
def _(energy, le, mo, ng):
    year_picker = mo.ui.dropdown(options=ng.gas_years(energy), value=ng.gas_years(energy)[1],
                                 label="Highlight gas year")
    cwv_picker = mo.ui.dropdown(options=list(le.LDZS), value="SE", label="LDZ")
    target_picker = mo.ui.radio(options={"A · exclude flagged days": "target", "B · repair missing feed": "target_repaired"},
                                value="A · exclude flagged days", label="Target", inline=True)
    mo.vstack([
        mo.md(r"""
        ## 4 · Weather drives demand

        Each point is one gas day: the official **Composite Weather Variable** (CWV — a blend of
        temperature and wind, roughly "how cold it feels") against the model target, total − DM.
        Against the official CWV, demand is **close to a straight line**. That is by design: the CWV
        formula already bends temperature (warm-weather cut-offs, wind chill, blending with seasonal
        normals) into a variable that demand responds to linearly. Rebuilding that bending from raw
        weather is the core of the model.

        Switch the target between **A** (flagged days excluded) and **B** (SE's missing feed repaired):
        for SE, B fills in the 2022/23 and 2023/24 winters. Before the offtake check, SE showed two
        separate bands here — the lower one was the under-reported total, not a change in behaviour.
        The CWV is only published per LDZ.
        """),
        mo.hstack([cwv_picker, year_picker, target_picker], justify="start", gap=2),
    ])
    return cwv_picker, target_picker, year_picker


@app.cell(hide_code=True)
def _(cwv_picker, energy, ng, target_picker, year_picker):
    ng.cwv_scatter(energy, cwv_picker.value, highlight=year_picker.value, target=target_picker.value)
    return


if __name__ == "__main__":
    app.run()
