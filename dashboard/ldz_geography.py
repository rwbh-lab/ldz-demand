import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", app_title="LDZ demand · LDZ geography", css_file="theme.css")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    from ldz_demand.charts import geography as geo_charts
    from ldz_demand.charts import style

    theme = style.use(style.theme_name_from_css(mo.notebook_dir() / "theme.css"))
    return geo_charts, mo


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # LDZ geography
    *Mapping the zones, and weighting the weather to where the gas is used.*

    The official Composite Weather Variable (CWV) takes each LDZ's weather from **a single weather
    station** — and some stations serve several LDZs: **East Anglia, North Thames and the South East
    all use Heathrow**; North West and North Wales share Rostherne in Cheshire. A station is a point;
    an LDZ is thousands of square kilometres of towns, hills and coast.

    This model instead takes weather from a **grid** (ERA5, ~28 km cells) and averages it over each
    LDZ, weighted to where gas is actually used. That needs two things this page builds and checks:
    **which places belong to which LDZ**, and **how to weight the grid inside each LDZ**.
    """)
    return


@app.cell(hide_code=True)
def _():
    from ldz_demand.geo import gas_use
    from ldz_demand.geo.ldz_membership import read_table

    las = read_table("ldz_local_authority.csv")
    towns = read_table("ldz_towns.csv")
    use = gas_use.load()
    return las, towns, use


@app.cell(hide_code=True)
def _(las, mo, towns):
    _m = las["method"].str.replace(r"_\d+km$", "", regex=True).str.replace(r"^override:.*", "override", regex=True).value_counts()
    _t = towns["method"].str.split("+").str[0].value_counts()
    _placed = int(_t.get("county", 0) + _t.get("footprint", 0))
    mo.vstack([
        mo.md(r"""
        ## 1 · Which places belong to which LDZ

        There is no public official LDZ boundary file, so membership is derived from three free sources:

        1. **Town lists per LDZ** (about 1,250 towns) from a gas broker's LDZ pages.
        2. **Where each town is**, from the ONS *Index of Place Names* — no geocoding. Places that share
           a name (there are several Newports) are told apart by the LDZ's listed counties, then by
           distance to that LDZ's other towns. Towns far from the rest of their LDZ but beside another
           LDZ's towns are treated as errors in the lists and left out.
        3. **Local authorities** take the LDZ their towns vote for. Where an authority's towns fall in
           two LDZs it is marked **split** — these are genuine boundary areas such as North Yorkshire,
           Shropshire and Buckinghamshire, and inside them each place will take the LDZ of its nearest
           listed town. Authorities with no listed town take the LDZ of the nearest one.
        """),
        mo.hstack([
            mo.stat(f"{_placed:,} / {len(towns):,}", label="Towns placed", caption=f"{int(_t.get('outlier', 0))} outliers excluded"),
            mo.stat(f"{int(_m.get('unanimous', 0) + _m.get('majority', 0) + _m.get('override', 0))}", label="Single-LDZ authorities",
                    caption=f"{int(_m.get('unanimous', 0))} unanimous · {int(_m.get('majority', 0))} majority · {int(_m.get('override', 0))} override"),
            mo.stat(f"{int(_m.get('split', 0))}", label="Split authorities", caption="boundary areas"),
            mo.stat(f"{int(_m.get('nearest_town', 0))}", label="No listed town", caption="nearest town's LDZ"),
        ], widths="equal", gap=1),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    from ldz_demand.config import create_config
    from ldz_demand.data import ldz_energy as le
    from ldz_demand.data.datasets import NG_LDZ_DAILY, NG_OFFTAKE_DAILY
    from ldz_demand.data.store import get_store

    try:
        _store = get_store(create_config())
        energy = le.energy_frame(_store.read(NG_LDZ_DAILY), _store.read(NG_OFFTAKE_DAILY))
        demand_note = None
    except Exception as exc:  # the map works without demand data; only the check below needs it
        energy, demand_note = None, exc
    return demand_note, energy


@app.cell(hide_code=True)
def _(energy, geo_charts, las, use):
    check = geo_charts.membership_check(las, use, energy)
    return (check,)


@app.cell(hide_code=True)
def _(energy, mo):
    method_picker = mo.ui.radio(options={"Local authority": "authority", "Voronoi (original)": "voronoi", "Hybrid": "hybrid"},
                                value="Hybrid", label="Method", inline=True)
    _views = {"LDZ": "ldz", "Confidence": "confidence"}
    if energy is not None:
        _views["Gap vs demand"] = "gap"
    view_picker = mo.ui.radio(options=_views, value="LDZ", label="Colour by", inline=True)
    towns_toggle = mo.ui.switch(value=False, label="Show listed towns")
    mo.vstack([
        mo.md(r"""
        ## 2 · The map

        Two ways to turn the town lists into a map:

        - **Local authority** — each authority takes the LDZ its towns vote for (this page's method).
          **Split** authorities are faded with a red outline; authorities with no listed town have an
          orange outline; **manual overrides** (from postcode checks, see §3) have a white outline. *Confidence*
          shows how decisive each vote was (local authority method only).
        - **Voronoi** — the original quant-lib method: every town gets the area closer to it than to any
          other town, smoothed and merged into LDZs. Boundaries follow the towns rather than
          administrative lines, so they are noisier — but they can cut through an authority.
        - **Hybrid** — whole authorities where an authority is clearly in one LDZ, and Voronoi cells only
          inside the split authorities, limited to the LDZs that authority's towns voted for. Each method
          is used where it is strong.

        **Gap vs National Gas demand** colours each LDZ by how far its share of GB gas use (under that
        method) is from its share of measured demand — see §3. Neighbouring LDZs always get different
        colours and every LDZ is labelled; hover for the evidence.
        """),
        mo.hstack([method_picker, view_picker], justify="start", gap=2),
        towns_toggle,
    ])
    return method_picker, towns_toggle, view_picker


@app.cell(hide_code=True)
def _(check, geo_charts, las, method_picker, mo, towns, towns_toggle, view_picker):
    _view = "ldz" if (view_picker.value == "confidence" and method_picker.value == "voronoi") else view_picker.value
    mo.ui.plotly(geo_charts.ldz_map(las, towns if towns_toggle.value else None, view=_view,
                                    method=method_picker.value, check=check), config={"scrollZoom": False})
    return


@app.cell(hide_code=True)
def _(mo):
    show_demand = mo.ui.checkbox(value=True, label="National Gas demand")
    show_authority = mo.ui.checkbox(value=True, label="Local authority")
    show_voronoi = mo.ui.checkbox(value=False, label="Voronoi (original)")
    show_hybrid = mo.ui.checkbox(value=False, label="Hybrid")
    return show_authority, show_demand, show_hybrid, show_voronoi


@app.cell(hide_code=True)
def _(check, demand_note, energy, geo_charts, mo, show_authority, show_demand, show_hybrid, show_voronoi):
    _methods = [m for m, box in (("authority", show_authority), ("voronoi", show_voronoi), ("hybrid", show_hybrid)) if box.value]
    mo.vstack([
        mo.md(r"""
        ## 3 · Does the map add up?

        A check that doesn't depend on how the map was made: add up the official **annual gas use**
        of every local authority (DESNZ statistics) by the LDZ our map puts it in, and compare each
        LDZ's share of GB with its share of **measured demand** from National Gas. A wrongly assigned
        area shows as one LDZ too high and a neighbour too low.

        Agreement to within ~1 percentage point is about as close as these sources allow: DESNZ
        leaves out some very large industrial sites and its "years" don't match gas years.

        **The source lists were checked postcode by postcode.** For each doubtful authority, a postcode
        in a test town was looked up on the broker's own postcode search
        (`docs/review/ldz_postcode_checks.csv`). Ten towns turned out to be listed under the wrong LDZ
        and are corrected for all three methods (`town_corrections.csv`):

        - all of **South Yorkshire** (Sheffield, Barnsley, Doncaster) is **EM**, not NE;
        - **Oldham** and **Buxton** are **NW**, as are **Chester** and **Malpas** (listed WN);
        - **Reading**, **Wokingham** and **Brackley** are **SO**.

        **Wiltshire** is genuinely split, with Salisbury in SO and Chippenham in SW, so it is marked split
        even though 81% of its towns vote SW.

        **A lesson in not fitting to the check.** Before the postcode checks, SO was about 2 pp short, so
        seven authorities around it were moved to SO, chosen *from* this check. That cut the gap almost
        as much as the postcode checks did, but the postcode search says four of the seven were wrong:
        Swindon, north Wiltshire, Windsor & Maidenhead and Slough are not SO. The checked map scores about
        the same overall, and every change is now backed by evidence. NE's +1.3 pp excess and NW's
        −0.7 pp shortfall have gone.

        | Local authority method | Source lists only | Provisional overrides | Postcode-checked |
        |---|---|---|---|
        | Mean absolute gap (pp) | 0.75 | 0.55 | 0.52 |
        | RMS gap (pp) | 0.93 | 0.66 | 0.67 |

        **Still open:** under the local-authority and hybrid methods, SO is still 1.2–1.5 pp short, SW is
        0.6–0.8 pp over and EA is 1.0–1.3 pp over. Candidates are where Wiltshire's SO/SW line runs,
        West Berkshire, and London's EA/NT edge. The unfinished checks are listed in the review file
        (the broker site's search limit stopped this round).

        **Methods compared:** Voronoi still breaks **London** (NT −2.4, SE +2.6 pp). London's boroughs
        aren't listed as towns, so the cells of surrounding towns carve the city up. It is better on EA and EM,
        though. The **hybrid** keeps London right and has the smallest RMS gap (0.61 pp vs 0.67 local
        authority, 1.08 Voronoi): its worst errors are the smallest. It is the map used from here on, with
        the other two kept for comparison.
        """),
        mo.hstack([show_demand, show_authority, show_voronoi, show_hybrid], justify="start", gap=2),
        geo_charts.membership_check_chart(check, methods=_methods, show_demand=show_demand.value and energy is not None)
        if energy is not None else mo.callout(mo.md(
            f"National Gas demand not loaded, so only our map's shares are available. `{demand_note}`"), kind="info"),
        mo.md("**Gap to measured demand by LDZ** (percentage points; + means our map gives the LDZ too much). "
              "Rows follow the chart, top to bottom.") if energy is not None else mo.md(""),
        mo.ui.table(geo_charts.gap_table(check).reset_index().rename(columns={"index": "LDZ"}), selection=None,
                    pagination=False, show_column_summaries=False, show_data_types=False, show_search=False)
        if energy is not None else mo.md(""),
    ])
    return


@app.cell(hide_code=True)
def _(las, mo, towns):
    _split = las[las["method"] == "split"][["lad23nm", "main_ldz", "votes", "n_towns"]].sort_values("n_towns", ascending=False)
    _fallback = las[las["method"].str.startswith("nearest_town")][["lad23nm", "ldz", "method"]]
    _unplaced = towns[towns["method"].str.split("+").str[0].isin(["ambiguous", "not_in_ipn", "outlier"])][["ldz", "town", "method"]]
    mo.accordion({
        f"Split authorities ({len(_split)})": mo.ui.table(_split, page_size=12, selection=None),
        f"No listed town — nearest town's LDZ ({len(_fallback)})": mo.ui.table(_fallback, selection=None),
        f"Towns not used ({len(_unplaced)})": mo.ui.table(_unplaced, page_size=12, selection=None),
        "How this was built": mo.md(r"""
        - Rebuild: `python -m ldz_demand.geo fetch` then `python -m ldz_demand.geo build`.
        - Tables: `ldz_demand/geo/data/ldz_local_authority.csv` and `ldz_towns.csv`; manual decisions go in
          `la_overrides.csv`, towns listed under the wrong LDZ in `town_corrections.csv`, town name fixes in
          `town_aliases.csv`, wrong source counties in `county_corrections.csv`. Postcode evidence:
          `docs/review/ldz_postcode_checks.csv`.
        - An authority is single-LDZ if one LDZ has ≥ 80% of its town votes; a town spanning several
          authorities votes for each in equal parts.
        - Code: `ldz_demand.geo.ldz_membership`, `ldz_demand.charts.geography`.
        """),
        "Sources & attribution": mo.md(
            "Town lists per LDZ: energybrokers.co.uk (used as evidence; not an official boundary). "
            "Place locations and local authorities: ONS Index of Place Names, July 2024. Boundaries: ONS Local "
            "Authority Districts, December 2023 (BUC); contains OS data © Crown copyright and database right 2023. "
            "Gas use: DESNZ subnational gas consumption statistics, 2024. All ONS/DESNZ data under the Open "
            "Government Licence v3.0. Coastline: Natural Earth (public domain)."),
    })
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4 · Weighting the weather — 🚧 next

    With membership settled, each LDZ's weather is an average of the grid cells inside it. *How* to
    weight those cells is a modelling choice, so several are built and compared by how well each
    explains demand — not by how plausible it looks:

    | Variant | Weights | What it tests |
    |---|---|---|
    | **Station point** | The grid cell at the official CWV station | The official approach, on the same weather data |
    | **Land mean** | Every land cell equally | Does weighting help at all? |
    | **Settlement density** | Density of the listed towns | The original idea, rebuilt |
    | **Population** | Census population | Where people live |
    | **Gas use** | Domestic gas meters / consumption | Where gas is used — off-grid areas count for nothing |
    """)
    return


if __name__ == "__main__":
    app.run()
