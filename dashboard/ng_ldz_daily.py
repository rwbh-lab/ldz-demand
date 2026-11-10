import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · National Gas data", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import ng_ldz_daily as ng
    from ldz_demand.charts import pages, style
    from ldz_demand.data import ldz_energy as le

    _theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    DECISIONS = "https://github.com/rwbh-lab/ldz-demand/blob/main/docs/decisions.md"
    Q, Q1, Q6 = pages.Q, pages.Q_at(1), pages.Q_at(6)
    return DECISIONS, Q, Q1, Q6, le, mo, ng, pages


@app.cell(hide_code=True)
def _(Q, mo, pages):
    pages.header("ng_ldz_daily.py", mo.md(r"""
    # National Gas LDZ data
    *Five years of daily demand per LDZ as published, and the target the model predicts, built from it.*
    """), mo.md(rf"""
    **The published data is complete from October 2021, and one figure in it is wrong: South East's total
    misses a steady ~31 GWh/day input for 18 months.** Those days are repaired, so they can train the model,
    and never used to score it. The model predicts {Q}: total demand minus daily-metered, both metered.

    - **Part I · Published data**: what National Gas publishes, and whether it adds up.
    - **Part II · From published data to the model target**: our own checks, the repair, and {Q}.
    """), notation=True)
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
            "**No National Gas data found.** Build it first — see the [user guide, §5.1](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_guide.md#51-national-gas):\n\n"
            "```bash\npython -m ldz_demand.data.ingest.national_gas refresh\n"
            "python -m ldz_demand.data.build.ng_ldz_daily\n"
            "python -m ldz_demand.data.build.ng_offtake_daily\n```"
            + (f"\n\nError: `{load_error}`" if load_error else "")
        ), kind="warn"),
    )
    has_offtakes = offtakes is not None and not offtakes.empty
    return has_offtakes, offtakes, raw


@app.cell(hide_code=True)
def _(has_offtakes, le, mo, offtakes, pages, raw):
    energy = le.energy_frame(raw, offtakes if has_offtakes else None)
    _ldz = energy.drop(index=le.GB, level="ldz")
    _flags = _ldz["flag"].value_counts()
    _days = raw["gas_day"]
    _bad = int((_ldz["flag"] != "ok").sum())

    mo.vstack([
        mo.Html(pages.tiles([
            ("History", f"{(_days.max() - _days.min()).days / 365.25:.1f}", f"{_days.min():%d %b %Y} → {_days.max():%d %b %Y}",
             "years"),
            ("Zones", f"{raw['ldz'].nunique()}", f"{raw['item'].nunique()} items each", "LDZs"),
            ("Values", f"{raw['value'].notna().sum():,}",
             "ng_ldz_daily" + (f" + {offtakes['value'].notna().sum():,} offtake" if has_offtakes else "")),
            ("Flagged LDZ-days", f"{_bad}",
             " · ".join(f"{_flags.get(f, 0)} {f.replace('_', ' ')}" for f in le.FLAGS[1:] if _flags.get(f, 0))),
        ])),
        mo.md("") if has_offtakes else mo.callout(mo.md(
            "Offtake data not loaded, so the offtake checks are off and the simpler ratio rule is used. "
            "Run `python -m ldz_demand.data.ingest.national_gas refresh --series offtakes` then "
            "`python -m ldz_demand.data.build.ng_offtake_daily`."), kind="info"),
    ])
    return (energy,)


@app.cell(hide_code=True)
def _(Q1, Q6, mo, ng, pages, raw):
    mo.vstack([
        mo.md("# Part I · Published data"),
        mo.md(f"""{pages.heading("Coverage", "Every core series is complete from October 2021")}

    - **Unidentified gas (UIG)** is only published from March 2025.
    - The latest ~6 days have only the provisional {Q1}; the closed-out {Q6} arrives six days after the
      gas day.
    """),
        mo.accordion({"Coverage by series and day (chart)": ng.coverage(raw)}),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(le, mo, pages):
    ldz_picker = mo.ui.dropdown(options=[le.GB, *le.LDZS], value=le.GB, label="Zone (this and the next chart)")
    mo.vstack([
        mo.md(f"""{pages.heading("Composition", "Homes and small business make the seasonal swing; daily-metered demand is flat")}

    - **Daily-metered** (DM): large industry and business, fairly flat through the year.
    - **Non-daily-metered** (NDM): homes and small business, strongly seasonal.
    - The thin line is the published total; the space above the stacked parts is gas they don't account
      for (next section). Click *NTS offtakes* in the legend to compare with the gas metered in from the
      national transmission system.
    """),
        mo.accordion({"More detail": mo.md(r"""
        Total demand is metered as gas enters each LDZ. It splits into **daily-metered** sites (large
        industry and business — fairly flat) and **non-daily-metered** demand (homes and small business —
        strongly seasonal). Total demand is published as a volume (mcm), so it is converted to energy with
        each day's calorific value; everything here is GWh/day. The zone picker drives this chart and the
        next; the checks in Part II have their own, since they work per LDZ.
        """)}),
        ldz_picker,
    ], gap=0.5)
    return (ldz_picker,)


@app.cell(hide_code=True)
def _(energy, ldz_picker, ng):
    ng.composition(energy, ldz_picker.value)
    return


@app.cell(hide_code=True)
def _(mo, pages):
    gap_units = mo.ui.radio(options={"GWh / day": False, "% of total": True}, value="GWh / day",
                            label="Units", inline=True)
    mo.vstack([
        mo.md(f"""{pages.heading("Adding up", "The published parts leave ~0.6–1 GWh/day per LDZ unexplained: shrinkage")}

    - **Total − DM − NDM** is unidentified gas plus LDZ shrinkage (leakage and own use).
    - From March 2025, with UIG published, it can be taken out too, leaving **shrinkage alone**: steady,
      ~0.3% of winter demand and ~1.5% of summer.
    - Flagged days (✕, see *Checks* below) are excluded.
    """),
        gap_units,
    ], gap=0.5)
    return (gap_units,)


@app.cell(hide_code=True)
def _(energy, gap_units, ldz_picker, ng):
    ng.gap(energy, ldz_picker.value, as_pct=gap_units.value)
    return


@app.cell(hide_code=True)
def _(DECISIONS, Q, Q6, has_offtakes, mo, pages):
    _part2 = rf"""
    ---

    # Part II · From published data to the model target

    /// admonition | Derived by this project
        type: info

    Everything from here on is our own processing of the published data: checks, a repair, and the
    construction of the **target** {Q}, the demand the model is fitted to and forecasts. Code:
    `ldz_demand.data.ldz_energy`. Decisions: [P1]({DECISIONS}#p1-target-total--dm-not-ndm), [P2]({DECISIONS}#p2-repair-the-se-missing-feed-target-b).
    ///

    {pages.heading("Target", f"{Q} is total minus daily-metered: both metered, so no CWV inside it")}

    - {Q} is the weather-sensitive part of demand: homes and small business, plus unidentified gas and
      shrinkage, in GWh/day at close-out ({Q6}).
    - Not the published **NDM**: National Gas *allocates* that with the official CWV, so fitting a weather
      model to it would partly fit the CWV to its own output.
    """
    mo.md(_part2 + (rf"""
    {pages.heading("Checks", "South East's published total misses a ~31 GWh/day input, September 2022 to February 2024")}

    - The gas metered in at the 122 NTS offtakes covers ~94–103% of each LDZ's total on a typical day,
      except **South East (~70%)**, which takes a steady ~31 GWh/day from a non-NTS input.
    - For 18 months that input **vanishes from South East's published total**, then returns; nothing else
      moves to compensate.
    - Because the input is so steady, those days can be **repaired** (offtakes + its usual level, ±5 GWh/day)
      or **excluded** (next section). Pick an LDZ to see its day-by-day check.
    """ if has_offtakes else rf"""
    {pages.heading("Checks", "Need the offtake data")}

    *See the note at the top of the page.*
    """))
    return


@app.cell(hide_code=True)
def _(energy, has_offtakes, le, mo, ng):
    feed_picker = mo.ui.dropdown(options=list(le.LDZS), value="SE", label="LDZ")
    mo.vstack([
        mo.accordion({"Offtake share of each LDZ's total (chart)": ng.offtake_share(energy)}),
        feed_picker,
    ], gap=0.5) if has_offtakes else None
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
        - Code: `ldz_demand.data.ldz_energy` (data), `ldz_demand.charts.ng_ldz_daily` (charts) · data: [user guide, §4.1](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/user_guide.md#41-national-gas--ldz-demand-calorific-value-cwv-nts-offtakes-forecasts).
        """),
    })
    return


@app.cell(hide_code=True)
def _(energy, le, mo, pages):
    _t = le.target_summary(energy)
    _names = {"days": "Days", "missing_feed": "Missing feed", "mismatch": "Mismatch", "invalid": "Invalid",
              "suspect": "Suspect", "target_a": "Target A", "target_b": "Target B", "repaired": "Repaired"}
    _rows = ["| LDZ | " + " | ".join(_names[c] for c in _t.columns) + " |", "|---" * (len(_t.columns) + 1) + "|"]
    for _ldz, _r in _t.iterrows():
        _cells = [f"{int(v):,}" for v in _r]
        _b = "**" if _r["repaired"] else ""  # the LDZ whose target B differs
        _rows.append(f"| {_b}{_ldz}{_b} | " + " | ".join(f"{_b}{c}{_b}" for c in _cells) + " |")
    mo.vstack([
        mo.md(f"""{pages.heading("Targets A and B", "The model uses B: repaired South East days train it, and never score it")}

    - **A** drops every flagged day; **B** does the same but repairs the days a feed is missing from the
      published total. In practice only South East's, September 2022 to February 2024.
    - On days real in both, A and B score the same; B gives South East back its 2022/23 data, and GB a
      third test year.
    - Repaired days are rougher than measured ones (errors ~10 against ~6 GWh/day), so they are never scored.
    """),
        mo.accordion({"More detail": mo.md(r"""
        Flagged days can't be used as they stand. **The model uses B.** On days that are real in both, the
        two give the same scores; but A leaves SE almost no data for 2022/23, and B gives it back — and with
        it a third test year for GB, which changed the choice of how the model follows behaviour over time
        ([results, experiment 6](https://github.com/rwbh-lab/ldz-demand/blob/main/docs/results.md#experiment-6-target-a-vs-b)).
        Repaired days are rougher than measured ones (errors ~10 vs ~6 GWh/day), so they train the model
        but are never used to score it.
        """)}),
        mo.md("\n".join(_rows)),
        mo.md("*Gas days per LDZ with a published total; flagged days by reason; the days each target keeps.*"),
    ], gap=0.5)
    return


@app.cell(hide_code=True)
def _(Q, energy, le, mo, ng, pages):
    year_picker = mo.ui.dropdown(options=ng.gas_years(energy), value=ng.gas_years(energy)[1],
                                 label="Highlight gas year")
    cwv_picker = mo.ui.dropdown(options=list(le.LDZS), value="SE", label="LDZ")
    target_picker = mo.ui.radio(options={"A · exclude flagged days": "target", "B · repair missing feed": "target_repaired"},
                                value="B · repair missing feed", label="Target", inline=True)
    mo.vstack([
        mo.md(f"""{pages.heading("Against the CWV", f"{Q} is close to a straight line in the official CWV")}

    - Each point is one gas day: the official **Composite Weather Variable** (roughly "how cold it feels")
      against {Q}.
    - The line is straight by design: the CWV formula bends temperature (warm-weather cut-off, wind chill,
      seasonal normals) so demand responds linearly. Rebuilding that bending from raw weather is the model.
    - Switch the target between **B** (used) and **A**: for South East, B fills in the 2022/23 and 2023/24
      winters. Before the check above, South East showed two bands here; the lower was the under-reported
      total, not a change in behaviour.
    """),
        mo.hstack([cwv_picker, year_picker, target_picker], justify="start", gap=2, wrap=True),
    ], gap=0.5)
    return cwv_picker, target_picker, year_picker


@app.cell(hide_code=True)
def _(cwv_picker, energy, ng, target_picker, year_picker):
    ng.cwv_scatter(energy, cwv_picker.value, highlight=year_picker.value, target=target_picker.value)
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.charts import pages as _pages_foot
    _pages_foot.footer(definitions=True)
    return


if __name__ == "__main__":
    app.run()
