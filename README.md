# ldz-demand

**Weather-driven gas demand for Great Britain's 13 Local Distribution Zones (LDZs)** — rebuilt from
gridded weather, weighted to where gas is used, and forecast two weeks ahead from every member of the
ECMWF ensemble. Free, public data only.

The industry forecasts LDZ demand from the **Composite Weather Variable** (CWV), built from one weather
station per LDZ — Heathrow for three of them. This project rebuilds the weather from ERA5 reanalysis,
averaged over each LDZ and weighted by local gas use, refits the CWV's form to five years of measured
demand, and turns each day's 50-member ensemble into a demand distribution per LDZ.

## Results

Out of sample — each gas year predicted only from the years before it — for GB (the 13 LDZs summed):

| | Ours | Benchmark |
|---|---|---|
| Error vs the **official CWV**, same regression, all days (RMSE) | **46.2** GWh/day | 50.8 (−9%) |
| … in winter | **52.6** | 67.2 (−22%) |
| … on the coldest 5% of days | **65.8** | 92.3 (−29%) |
| Winter error per gas day vs **National Gas's published day-ahead forecasts** | **1.9–2.2%** | 3.2–3.6% |

Better than the official CWV in 10 of the 13 LDZs. Over all days, about level with National Gas's
forecasts (they are better in summer, ours in winter) — not yet like for like: ours here uses actual
weather, theirs a day-ahead forecast. Details: [docs/results.md](docs/results.md).

## How it works

```
Sources            Datasets                Pre-CWV models                 CWV model          Outputs
National Gas  ──►  LDZ demand, offtakes ─► target (total − DM) ──────┐
                   their forecasts ──────────────────────────────────┼───────────────────► benchmark
ONS, DESNZ, OS ──► geography ──────────► LDZ map ─► grid weights     │
Copernicus    ──►  ERA5 hourly ──────────────────► LDZ weather ──────┼─► CWV + demand ───► results
ECMWF         ──►  ensemble runs ────────────────► ensemble LDZ ─────┘   model ─────────► demand forecasts
                                                   weather
```

- **Target:** total LDZ demand minus daily-metered demand — not the published NDM, which is allocated
  from the official CWV itself. Published totals are checked against the gas metered into each LDZ.
- **LDZ weather:** ERA5 grid cells over each LDZ, weighted by DESNZ gas use, on the 05:00 – 05:00 gas
  day, with the heating hours weighted up.
- **CWV model:** the official CWV's structure — effective temperature, wind chill, solar, a seasonal
  shape shared by all LDZs, summer cut-off, cold-weather upturn — refitted per LDZ; demand linear in it
  plus calendar effects; recent years weighted more.
- **Forecasts:** the fitted model on each ensemble member, with intervals that add the model's own
  out-of-sample error to the weather's spread.

The dashboard's **Project map** draws this flow interactively, with the code behind every step.

## Quick start

Python 3.12. No database or server needed: processed tables are written as CSV files by default.

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[all,dev]"
python -m pytest
```

Then get the data and build the tables (the fitted model and the LDZ geography ship with the package):

```bash
python -m ldz_demand.data.ingest.national_gas refresh     # National Gas: demand, offtakes, forecasts
python -m ldz_demand.data.build.ng_ldz_daily
python -m ldz_demand.data.build.ng_offtake_daily
python -m ldz_demand.data.build.ng_forecast_daily
python -m ldz_demand.data.ingest.era5 refresh             # ERA5: needs a free Copernicus account (config/cdsapirc.example)
python -m ldz_demand.data.build.weather_ldz_daily
python -m ldz_demand.dashboard                            # http://localhost:2718
```

For forecasts, archive ensemble runs as they are published (`ldz_demand.data.ingest.ecmwf_ens refresh`,
then `data.build.ens_ldz_daily` and `models.forecast --missing`). The full walkthrough — every dataset,
timings, the optional MySQL backend and the scheduled jobs — is in [docs/user_guide.md](docs/user_guide.md).

## The dashboard

`python -m ldz_demand.dashboard` serves every page from one local server (marimo):

| Section | Pages |
|---|---|
| Project | Overview (a short write-up) · Project map |
| Data | National Gas data (with how the model target is built) · ERA5 weather |
| Pre-CWV models | LDZ geography · LDZ weather · Ensemble LDZ weather |
| CWV model | Demand model — each part of the model, with its fitted values |
| Outputs | Results · Demand forecasts |

## Documentation

- [docs/methodology.md](docs/methodology.md) — the method, and why it is built this way
- [docs/decisions.md](docs/decisions.md) — each modelling choice, the alternatives, and the evidence
- [docs/results.md](docs/results.md) — every experiment and its scores
- [docs/user_guide.md](docs/user_guide.md) — building the data, running the jobs, every command

## Repository layout

```
src/ldz_demand/
  data/ingest/       download and archive each source (National Gas, ERA5, ECMWF ensemble)
  data/build/        archive -> tables (rebuildable from the archive); gas-day statistics
  data/store/        one Store interface: CSV files (default) or MySQL
  data/ldz_energy.py demand in energy, data-quality flags, the model target
  geo/               the LDZ map and grid weights; small derived reference tables in geo/data/
  models/            CWV form, demand fit, experiments, final fit, forecasts, results bundle
  charts/            Plotly charts and the shared theme; the project map
  project_map.py     the pipeline as data (a test checks it matches the code)
  db/                MySQL connection, DDL, migration runner
dashboard/           marimo pages
db/migrations/       versioned SQL migrations
deploy/nas/          scheduled jobs for a home server (daily ensemble; weekly refresh + forecasts)
docs/                methodology, decisions, results, user guide
tests/
```

## Licence

The code is under the [MIT licence](LICENSE). The data is not: it stays under its sources' own terms,
listed below.

## Data sources and licences

Raw data is never committed; it is downloaded from the sources below. The small derived tables that ship
with the package say what they come from in their headers.

- **National Gas** data portal (data.nationalgas.com) — LDZ demand, CWV, NTS offtakes, demand forecasts.
- **ERA5** — Copernicus Climate Change Service. Contains modified Copernicus Climate Change Service
  information; neither the European Commission nor ECMWF is responsible for any use of it.
- **ECMWF open data** — ensemble forecasts, CC BY 4.0.
- **ONS** Index of Place Names and local authority boundaries; **DESNZ** sub-national gas consumption;
  **Ordnance Survey** Code-Point Open — Open Government Licence v3.0. Contains OS data © Crown copyright
  and database right.
- **Methodology references:** National Gas, *Gas Demand Forecasting Methodology* (2016); Xoserve,
  *Composite Weather Variable* (2026).
- LDZ town lists (`geo/data/ldz_towns.csv`) compiled from energybrokers.co.uk, with thanks, and used as
  evidence for the LDZ map; postcode checks against the SGN and Wales & West Utilities postcode checkers.

---

Robert Hemming, 2026. Planned and built with Claude as a development partner.
