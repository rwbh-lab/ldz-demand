import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · National Gas data", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import ng_ldz_daily as ng
    from ldz_demand.charts import style

    theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return mo, ng


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # National Gas LDZ data

    Daily gas demand for each of GB's 13 Local Distribution Zones (LDZs), as published by National Gas.
    This page checks the raw data before any modelling: **what is there, whether the parts add up,
    and how demand responds to weather.**

    The model's target is **total demand minus daily-metered (DM) demand** — the weather-sensitive
    part, built from metered quantities rather than the published NDM allocation (which is itself
    calculated from the official weather variable, so fitting to it would be circular).
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.config import create_config
    from ldz_demand.data.datasets import NG_LDZ_DAILY
    from ldz_demand.data.store import get_store

    try:
        raw = get_store(create_config()).read(NG_LDZ_DAILY)
        load_error = None
    except Exception as exc:  # show setup help instead of a traceback
        raw, load_error = None, exc

    mo.stop(
        raw is None or raw.empty,
        mo.callout(mo.md(
            "**No National Gas data found.** Build it first — see `docs/user_guide.md` §5.1:\n\n"
            "```bash\npython -m ldz_demand.data.ingest.national_gas refresh\n"
            "python -m ldz_demand.data.build.ng_ldz_daily\n```"
            + (f"\n\nError: `{load_error}`" if load_error else "")
        ), kind="warn"),
    )
    return (raw,)


@app.cell(hide_code=True)
def _(mo, ng, raw):
    energy = ng.energy_frame(raw)
    _ldz = energy.drop(index=ng.GB, level="ldz")
    _flags = _ldz["flag"].value_counts()
    _days = raw["gas_day"]

    mo.hstack([
        mo.stat(f"{(_days.max() - _days.min()).days / 365.25:.1f} years", label="History",
                caption=f"{_days.min():%d %b %Y} → {_days.max():%d %b %Y}"),
        mo.stat(f"{raw['ldz'].nunique()} LDZs", label="Zones", caption=f"{raw['item'].nunique()} items each"),
        mo.stat(f"{raw['value'].notna().sum():,}", label="Values", caption="ng_ldz_daily rows with a value"),
        mo.stat(f"{_flags.get('suspect', 0) + _flags.get('invalid', 0)}", label="Flagged LDZ-days",
                caption=f"{_flags.get('suspect', 0)} suspect · {_flags.get('invalid', 0)} invalid"),
    ], widths="equal", gap=1)
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
def _(mo, ng):
    ldz_picker = mo.ui.dropdown(options=[ng.GB, *ng.LDZS], value=ng.GB, label="Zone")
    closeout_picker = mo.ui.radio(options={"D+6 (closed out)": "d6", "D+1 (provisional)": "d1"},
                                  value="D+6 (closed out)", label="Values", inline=True)
    mo.vstack([
        mo.md(r"""
        ## 2 · What demand is made of

        Total demand is metered at the points where gas enters each LDZ. It splits into
        **daily-metered** sites (large industry and business — fairly flat) and **non-daily-metered**
        demand (homes and small business — strongly seasonal). Total demand is published as a volume
        (mcm), so it is converted to energy with each day's calorific value; everything below is GWh/day.

        The thin line is the total; the space between it and the stacked parts is gas the parts don't
        account for (§3). Use the zone picker for any LDZ, or the GB sum.
        """),
        mo.hstack([ldz_picker, closeout_picker], justify="start", gap=2),
    ])
    return closeout_picker, ldz_picker


@app.cell(hide_code=True)
def _(closeout_picker, ng, raw):
    zone_energy = ng.energy_frame(raw, closeout=closeout_picker.value)
    return (zone_energy,)


@app.cell(hide_code=True)
def _(ldz_picker, ng, zone_energy):
    ng.composition(zone_energy, ldz_picker.value)
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
        demand but ~1.5% in summer.

        Some published totals are clearly wrong. Days where the total is below 10% of DM + NDM are
        **invalid** (zero or negative totals); below 70% are **suspect** — notably long spells in SE
        (Aug–Nov 2022, May–Oct 2023) where the total runs at about half its parts, as if part of the
        metered total is missing. Flagged days (✕) are excluded from the model target.
        """),
        gap_units,
    ])
    return (gap_units,)


@app.cell(hide_code=True)
def _(energy, gap_units, ldz_picker, ng):
    ng.gap(energy, ldz_picker.value, as_pct=gap_units.value)
    return


@app.cell(hide_code=True)
def _(energy, mo, ng):
    _flagged = ng.flagged_days(energy)
    mo.accordion({
        f"Flagged LDZ-days ({len(_flagged)}) — table": mo.ui.table(_flagged, page_size=12, selection=None),
        "How this was computed": mo.md(rf"""
        - Energy: `total_GWh = total_mcm × CV / 3.6`; DM, NDM and UIG are published in kWh (÷ 10⁶).
        - `ratio = total / (DM + NDM)`; **invalid** if < {ng.INVALID_BELOW}, **suspect** if < {ng.SUSPECT_BELOW}.
        - GB = sum of the 13 LDZs; a GB day takes the worst flag of its LDZs.
        - Residual flags (> 5% of total) only apply from March 2025, when UIG exists.
        - Code: `ldz_demand.charts.ng_ldz_daily` · data: `docs/user_guide.md` §4.1.
        """),
    })
    return


@app.cell(hide_code=True)
def _(energy, mo, ng):
    year_picker = mo.ui.dropdown(options=ng.gas_years(energy), value=ng.gas_years(energy)[1],
                                 label="Highlight gas year")
    mo.vstack([
        mo.md(r"""
        ## 4 · Weather drives demand

        Each point is one gas day: the official **Composite Weather Variable** (CWV — a blend of
        temperature and wind, roughly "how cold it feels") against the model target, total − DM.
        Demand falls steeply as CWV rises, then **flattens** above ~15 °C, where heating switches off.
        That bend — and how the curve steepens in the cold — is what the model has to capture.

        The CWV is only published per LDZ, so pick a zone (GB has no single CWV).
        """),
        year_picker,
    ])
    return (year_picker,)


@app.cell(hide_code=True)
def _(energy, ldz_picker, mo, ng, year_picker):
    _zone = "SE" if ldz_picker.value == ng.GB else ldz_picker.value
    mo.vstack([
        mo.md(f"*Showing LDZ {_zone}*" + (" — GB is selected above, so SE is shown." if ldz_picker.value == ng.GB else "")),
        ng.cwv_scatter(energy, _zone, highlight=year_picker.value),
    ])
    return


if __name__ == "__main__":
    app.run()
