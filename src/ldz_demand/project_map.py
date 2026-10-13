"""
The project map: how data flows from public sources, through the pre-CWV models, into the CWV demand
model and its outputs — as data, drawn by ldz_demand.charts.project_map on the dashboard's Project map
page.

Boxes (Node) are things: a source, a dataset, a model, an output. Arrows (Edge) are processes: ingest,
build, fit, score. Each names the modules, commands, tables, files, config sections and dashboard
pages behind it; tests/test_project_map.py checks that every one of those exists, and that every module
in the package appears somewhere on the map — so the map can't silently go out of date.
"""

from dataclasses import dataclass, field

COLUMNS = ("Sources", "Datasets", "Pre-CWV models", "CWV model", "Outputs")


@dataclass(frozen=True)
class Node:
    id: str
    column: int | None               # index into COLUMNS; None: the supporting strip underneath
    row: float                       # horizontal layout: position down the column
    title: str
    summary: str                     # one or two sentences
    details: tuple[tuple[str, str], ...] = ()   # (label, text) shown in the panel
    modules: tuple[str, ...] = ()    # dotted module names under ldz_demand
    datasets: tuple[str, ...] = ()   # table names (ldz_demand.data.datasets)
    files: tuple[str, ...] = ()      # paths relative to the project root
    page: str | None = None          # dashboard page file (ldz_demand.charts.pages.PAGES)
    docs: tuple[str, ...] = ()       # docs files, optionally "file: section"
    status: str = "built"            # built | planned
    at: tuple[float, float] | None = None  # vertical layout: (lane across, depth down), in box units


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    process: str                     # short verb shown on hover: ingest, build, fit, ...
    summary: str
    commands: tuple[str, ...] = ()   # "python -m ldz_demand.x [args]"
    modules: tuple[str, ...] = ()
    config: tuple[str, ...] = ()     # sections of config/default.ini
    runs: str = ""                   # where / how often
    details: tuple[tuple[str, str], ...] = field(default=())
    status: str = "built"
    route: str = ""                  # vertical layout: "behind" — a straight drop, behind any box in the way

    @property
    def id(self) -> str:
        return f"{self.source}->{self.target}"


NODES: tuple[Node, ...] = (
    # --- Sources ---------------------------------------------------------------------------------------------
    Node("src_national_gas", 0, 0.5, "National Gas data portal",
         "Daily LDZ demand, calorific value, CWV, NTS offtakes and National Gas's own forecasts.",
         details=(("Where", "data.nationalgas.com, find-gas-data-download API (free, no key)"),
                  ("History", "a rolling five years: from 12 Oct 2021"),
                  ("Units", "total demand in mcm; DM / NDM / UIG in kWh; converted with the LDZ CV")),
         docs=("docs/user_guide.md: 4.1",),
         at=(0.55, 0)),
    Node("src_cds", 0, 3.0, "Copernicus CDS (ERA5)",
         "Hourly reanalysis weather on a 0.25° grid: temperature, wind, solar radiation, precipitation.",
         details=(("Where", "Copernicus Climate Data Store, reanalysis-era5-single-levels (free account)"),
                  ("History", "1940 to ~5 days ago; we use July 2021 onwards"),
                  ("Licence", "Copernicus licence; credited")),
         docs=("docs/user_guide.md: 4.2",),
         at=(3.2, 0)),
    Node("src_ecmwf", 0, 4.0, "ECMWF open data (ENS)",
         "The 00z ensemble each day: 50 members out to 15 days, 0.25°.",
         details=(("Where", "ECMWF open-data portal (or the AWS / Azure / Google mirrors)"),
                  ("Kept", "only the last few days on the portal, so archived daily"),
                  ("Members", "50 perturbed members; the open data has no control run")),
         docs=("docs/user_guide.md: 4.3",),
         at=(4.2, 0)),
    Node("src_geography", 0, 5.2, "Geography sources",
         "Town lists per LDZ, place index, boundaries, gas use by local authority, postcodes.",
         details=(("Town lists", "energybrokers.co.uk, one page per LDZ (credited, not republished)"),
                  ("ONS", "Index of Place Names; local authority boundaries (Dec 2023)"),
                  ("DESNZ", "sub-national gas consumption by local authority"),
                  ("OS", "Code-Point Open (every live GB postcode)"),
                  ("Operators", "SGN and WWU postcode checkers, for authorities on an LDZ boundary")),
         files=("src/ldz_demand/geo/data/cwv_stations.csv",),
         docs=("docs/methodology.md: 4.1",),
         at=(2.15, 0)),

    # --- Datasets --------------------------------------------------------------------------------------------
    Node("ds_ng_ldz", 1, 0.0, "LDZ demand & CWV",
         "Per LDZ and gas day: total, DM, NDM, UIG, CV, the official CWV.",
         datasets=("ng_ldz_daily",), page="ng_ldz_daily.py",
         details=(("Raw archive", "raw_dir/national_gas/ldz/ — every pull kept"),
                  ("Rule", "newest pull with a value wins; D+6 close-out values used for modelling")),
         at=(1.1, 1)),
    Node("ds_ng_offtake", 1, 1.0, "NTS offtakes",
         "Gas taken from the national transmission system into each LDZ (122 offtakes).",
         datasets=("ng_offtake_daily",),
         details=(("Raw archive", "raw_dir/national_gas/offtakes/"),
                  ("Used for", "checking the published total: total − offtakes should be near its usual level")),
         at=(0.55, 1.45)),
    Node("ds_ng_forecast", 1, 2.0, "National Gas forecasts",
         "Their total-demand forecast per LDZ (~8 issues a day) and their forecast CWV.",
         datasets=("ng_forecast_daily",),
         details=(("Raw archive", "raw_dir/national_gas/forecasts/ (fetched with latestFlag=N: every issue)"),
                  ("Used for", "the benchmark against our forecasts, matched by issue time")),
         at=(0, 1)),
    Node("ds_era5", 1, 3.0, "ERA5 hourly grid",
         "Monthly NetCDF files over GB: core (t2m, wind) and extra (solar, precipitation).",
         files=(), page="era5_weather.py",
         details=(("Where", "raw_dir/era5/YYYY/era5_gb_YYYY-MM.nc and era5x_gb_YYYY-MM.nc (no table)"),
                  ("Area", "61°N 8.5°W – 49.5°N 2°E"),
                  ("Note", "accumulations (solar, precipitation) are shifted by an hour to their gas day")),
         at=(3.2, 1)),
    Node("ds_ens", 1, 4.0, "Ensemble runs",
         "Each day's 00z run, cropped to GB on download: 2t, 10u/10v, ssrd, tp, min/max temperature.",
         details=(("Where", "raw_dir/ecmwf_ens/ — one file per run (no global files kept)"),
                  ("Steps", "3-hourly to 144 h, then 6-hourly to 360 h")),
         at=(4.2, 1)),
    Node("ds_geography", 1, 5.2, "Geography references",
         "Raw downloads, plus the small derived tables shipped with the package.",
         files=("src/ldz_demand/geo/data/ldz_towns.csv", "src/ldz_demand/geo/data/desnz_la_gas.csv",
                "src/ldz_demand/geo/data/lad23_buc_gb.geojson"),
         details=(("Raw", "raw_dir/reference/ (never committed)"),
                  ("Shipped", "ldz_demand/geo/data/: towns, corrections, DESNZ gas use, boundaries, stations")),
         at=(2.15, 1)),

    # --- Pre-CWV models --------------------------------------------------------------------------------------
    Node("m_target", 2, 0.5, "Target & data flags",
         "Demand in GWh, data-quality flags, and the model target: total − DM.",
         modules=("data.ldz_energy",), page="ng_ldz_daily.py",
         docs=("docs/methodology.md: 3",),
         details=(("Target A", "total − DM on days the published total passes the checks (the main target)"),
                  ("Target B", "as A, plus repaired days where a feed is missing from the total (sensitivity)"),
                  ("Flags", "invalid, suspect, mismatch, missing_feed (SE, Sep 2022 – Feb 2024)"),
                  ("Why not NDM", "published NDM is itself derived from the CWV, so would be circular"),
                  ("Also carries", "the official CWV, for the benchmark")),
         at=(1.1, 2.05)),
    Node("m_map", 2, 2.6, "LDZ map",
         "Which places belong to which LDZ — there is no public LDZ boundary file.",
         modules=("geo.ldz_membership", "geo.voronoi", "geo.hybrid", "geo.postcode_sample", "geo.boundaries"),
         files=("src/ldz_demand/geo/data/ldz_local_authority.csv", "src/ldz_demand/geo/data/ldz_postcode_sample.csv"),
         page="ldz_geography.py", docs=("docs/methodology.md: 4.1",),
         details=(("Methods", "local authority; Voronoi around listed towns; hybrid; postcode-sampled (used)"),
                  ("Postcode-sampled", "authorities on a boundary split by asking the operators about sampled postcodes"),
                  ("Finding", "the map method barely matters for weather (≤ 0.05 °C day to day)")),
         at=(2.15, 2.05)),
    Node("m_weights", 2, 3.6, "Grid weights",
         "How much each ERA5 grid cell counts towards each LDZ: by area, by gas use, or the official station.",
         modules=("geo.grid_weights", "geo.gas_use"),
         files=("src/ldz_demand/geo/data/ldz_cell_weights.csv",),
         docs=("docs/methodology.md: 4.2",),
         details=(("Variants", "membership (map method) × weighting (area, gas use); plus station/point"),
                  ("Used", "sampled/gas — postcode-sampled map, weighted by DESNZ gas use"),
                  ("Shared", "the same weights for ERA5 and the ensemble")),
         at=(2.15, 2.65)),
    Node("m_weather", 2, 4.6, "LDZ weather",
         "Gas-day weather per LDZ and variant: mean, min / max temperature, wind, solar, precipitation.",
         modules=("data.build.weather_ldz_daily", "data.build.weather_ldz_hourly", "data.build.gas_day"),
         datasets=("weather_ldz_daily", "weather_ldz_hourly"), page="ldz_weather.py",
         docs=("docs/methodology.md: 4.3",),
         details=(("Gas day", "05:00 – 05:00 UK time; time-weighted means"),
                  ("Finding", "the official stations differ from the gas-weighted LDZ by season (WS +0.85 °C in Nov)")),
         at=(3.2, 3.35)),
    Node("m_ens", 2, 5.6, "Ensemble LDZ weather",
         "The same per-LDZ gas-day weather for every ensemble member and lead day.",
         modules=("data.build.ens_ldz_daily",), datasets=("ens_ldz_daily",), page="ensemble_forecasts.py",
         details=(("Shape", "run date × member (50) × lead day (0 – 14) × LDZ × variant × variable"),
                  ("Gas day", "interpolated between 3- / 6-hourly steps; interval min / max for extremes")),
         at=(4.2, 3.35)),

    # --- CWV model -------------------------------------------------------------------------------------------
    Node("c_demand", 3, 3.4, "CWV demand model",
         "Our CWV per LDZ from gas-weighted weather, and demand as a straight line in it plus calendar terms.",
         modules=("models.cwv", "models.calendar", "models.demand"),
         docs=("docs/methodology.md: 5", "docs/results.md"),
         details=(("CWV", "effective temperature, wind chill, solar, a seasonal shape shared by all LDZs; "
                          "summer cut-off and cold-weather upturn"),
                  ("Demand", "a + b · CWV + day of week + bank holidays + Christmas; a and b per gas year"),
                  ("Fit", "robust (soft L1) least squares; CWV parameters bounded near the published values"),
                  ("Benchmark", "the official CWV through the same regression")),
         at=(1.1, 4.15)),

    # --- Outputs ---------------------------------------------------------------------------------------------
    Node("o_results", 4, 3.4, "Experiment results",
         "Held-out and forward predictions, scores and fitted parameters for each experiment.",
         modules=("models.experiment",), docs=("docs/results.md",),
         details=(("Where", "data/results/<experiment>_{predictions,scores,params}.csv (not committed)"),
                  ("Experiments", "1 weather input, 3 seasonal term, 4 change over time; 2, 5, 6 open"),
                  ("Best so far", "GB winter 2.5% per gas day, 2024/25 (official CWV 3.3%)")),
         at=(1.1, 5.15)),
    Node("o_benchmark", 4, 2.4, "National Gas benchmark",
         "Our model against National Gas's published day-ahead forecasts.",
         modules=("models.benchmark",), docs=("docs/results.md: Against National Gas's day-ahead forecasts",),
         details=(("Result", "level on average; winter 2.2% vs 3.2 – 3.6%; summer worse"),
                  ("Caveat", "ours on actual weather (small effect at day-ahead); theirs also forecasts DM"),
                  ("Where", "data/results/ng_forecast_comparison.csv")),
         at=(0, 5.15)),
    Node("o_forecast", 4, 4.8, "Demand forecasts",
         "Demand per LDZ for the next 15 days from each ensemble member: a distribution, not a point.",
         status="planned", docs=("docs/methodology.md: 8",),
         details=(("Plan", "run the fitted model on every member; compare with National Gas by issue time"),
                  ("Needs", "an ensemble archive covering at least one winter (the backfill)")),
         at=(4.2, 5.15)),

    # --- Supporting strip ------------------------------------------------------------------------------------
    Node("x_store", None, 0, "Store",
         "Where tables live: CSV cache by default, or MySQL on the NAS — behind one interface.",
         modules=("data.store", "data.store.base", "data.store.csv_cache", "data.store.mysql", "data.datasets"),
         details=(("Switch", "[storage] database = true in config/local.ini"),)),
    Node("x_db", None, 1, "MySQL & migrations",
         "Numbered SQL migrations and a runner for the MySQL tables.",
         modules=("db", "db.__main__", "db.connection", "db.ddl", "db.migrate"),
         details=(("Commands", "python -m ldz_demand.db status | migrate | draft DATASET"),)),
    Node("x_config", None, 2, "Config",
         "INI settings (default, local, docker) and project paths.",
         modules=("config",), files=("config/default.ini", "config/docker.ini")),
    Node("x_nas", None, 3, "NAS container",
         "The daily ensemble download and build, in Container Manager on the Synology NAS.",
         files=("Dockerfile", "deploy/nas/ens_daily.sh", "config/docker.ini"),
         details=(("Schedule", "DSM Task Scheduler, daily after the 00z run is published (~09:30 UTC)"),)),
    Node("x_dashboard", None, 4, "Dashboard",
         "The marimo pages, served together, and their shared charts and theme.",
         modules=("dashboard", "charts.pages", "charts.style", "charts.ng_ldz_daily", "charts.era5", "charts.geography",
                  "charts.coastline", "charts.weather_ldz", "charts.ensemble", "charts.project_map", "project_map"),
         details=(("Command", "python -m ldz_demand.dashboard (http://localhost:2718)"),)),
)

EDGES: tuple[Edge, ...] = (
    # sources -> datasets
    Edge("src_national_gas", "ds_ng_ldz", "ingest + build", "Download new gas days, archive them, build the table.",
         commands=("python -m ldz_demand.data.ingest.national_gas refresh --series ldz",
                   "python -m ldz_demand.data.build.ng_ldz_daily"),
         modules=("data.ingest.national_gas", "data.build.ng_ldz_daily"), config=("national_gas", "storage"),
         runs="Mac, by hand (a few minutes)"),
    Edge("src_national_gas", "ds_ng_offtake", "ingest + build", "The 122 NTS offtakes into the LDZs.",
         commands=("python -m ldz_demand.data.ingest.national_gas refresh --series offtakes",
                   "python -m ldz_demand.data.build.ng_offtake_daily"),
         modules=("data.ingest.national_gas", "data.build.ng_offtake_daily"), config=("national_gas",),
         runs="Mac, by hand"),
    Edge("src_national_gas", "ds_ng_forecast", "ingest + build", "Every issue of their demand and CWV forecasts.",
         commands=("python -m ldz_demand.data.ingest.national_gas refresh --series forecasts",
                   "python -m ldz_demand.data.build.ng_forecast_daily"),
         modules=("data.ingest.national_gas", "data.build.ng_forecast_daily"), config=("national_gas",),
         runs="Mac, by hand"),
    Edge("src_cds", "ds_era5", "ingest", "One request per month and variable group, queued at Copernicus.",
         commands=("python -m ldz_demand.data.ingest.era5 refresh",),
         modules=("data.ingest.era5",), config=("era5",),
         runs="Mac, by hand (~2 – 4 minutes a month; hours for the full history)"),
    Edge("src_ecmwf", "ds_ens", "ingest", "Download each step of the 00z run in parallel, cropping to GB on decode.",
         commands=("python -m ldz_demand.data.ingest.ecmwf_ens refresh",),
         modules=("data.ingest.ecmwf_ens",), config=("ecmwf_ens",),
         runs="NAS container, daily"),
    Edge("src_geography", "ds_geography", "fetch", "Download the reference files; ask the operators about sampled postcodes.",
         commands=("python -m ldz_demand.geo fetch", "python -m ldz_demand.geo.postcode_sample check"),
         modules=("geo", "geo.__main__", "geo.postcode_sample"),
         runs="Mac, once (the postcode checks are paced and resumable)"),
    # datasets -> pre-CWV models
    Edge("ds_ng_ldz", "m_target", "derive", "Convert to GWh, flag bad totals, form the target; the official CWV passes through.",
         modules=("data.ldz_energy",), runs="in memory, whenever a page or model loads demand"),
    Edge("ds_ng_offtake", "m_target", "check", "Total − offtakes against its usual level: finds the missing SE feed.",
         modules=("data.ldz_energy",), runs="in memory"),
    Edge("ds_geography", "m_map", "build", "Towns located with the ONS index, authorities labelled, boundaries split.",
         commands=("python -m ldz_demand.geo build",),
         modules=("geo.ldz_membership", "geo.voronoi", "geo.hybrid", "geo.postcode_sample", "geo.boundaries"),
         runs="Mac, once (outputs committed)"),
    Edge("m_map", "m_weights", "build", "Overlay the map on the ERA5 grid; weight places by area or gas use.",
         commands=("python -m ldz_demand.geo build",), modules=("geo.grid_weights", "geo.gas_use"),
         config=("ldz_weather",), runs="Mac, once (outputs committed)"),
    Edge("ds_geography", "m_weights", "weights", "DESNZ gas use per authority, and the official CWV stations.",
         modules=("geo.gas_use", "geo.grid_weights"), route="behind"),
    Edge("ds_era5", "m_weather", "build", "Weighted grid means per LDZ, then gas-day means and extremes.",
         commands=("python -m ldz_demand.data.build.weather_ldz_daily", "python -m ldz_demand.data.build.weather_ldz_hourly"),
         modules=("data.build.weather_ldz_daily", "data.build.weather_ldz_hourly", "data.build.gas_day"),
         config=("ldz_weather",), runs="Mac, after each ERA5 refresh (rebuilds whole months)"),
    Edge("m_weights", "m_weather", "weights", "The grid weights for each variant.", modules=("geo.grid_weights",)),
    Edge("ds_ens", "m_ens", "build", "The same weights and gas-day rules for each member and lead day.",
         commands=("python -m ldz_demand.data.build.ens_ldz_daily",),
         modules=("data.build.ens_ldz_daily", "data.build.gas_day"), config=("ldz_weather",),
         runs="NAS container, daily after the download"),
    Edge("m_weights", "m_ens", "weights", "The grid weights for each variant.", modules=("geo.grid_weights",)),
    # pre-CWV -> CWV model
    Edge("m_target", "c_demand", "target + official CWV",
         "What the model is fitted to — total − DM, GWh/day (target A) — and the published CWV alongside it, "
         "fitted the same way as the benchmark.",
         modules=("data.ldz_energy", "models.experiment", "models.demand")),
    Edge("m_weather", "c_demand", "weather", "Gas-weighted daily temperature, wind and solar per LDZ (sampled/gas).",
         modules=("models.experiment", "models.demand")),
    # CWV model -> outputs
    Edge("c_demand", "o_results", "fit + score", "Leave one gas year out, or forward; scored on the same days for every model.",
         commands=("python -m ldz_demand.models.experiment cwv_inputs", "python -m ldz_demand.models.experiment seasonal",
                   "python -m ldz_demand.models.experiment change"),
         modules=("models.experiment",), runs="Mac (a few minutes each)"),
    Edge("o_results", "o_benchmark", "compare", "Experiment 4's best model on the same days as their forecasts.",
         commands=("python -m ldz_demand.models.benchmark",), modules=("models.benchmark",), runs="Mac (seconds)"),
    Edge("ds_ng_forecast", "o_benchmark", "benchmark", "Their first day-ahead issue (~13:00 on D−1), converted to GWh.",
         modules=("models.benchmark",)),
    Edge("c_demand", "o_forecast", "forecast", "The fitted model, run on each ensemble member.", status="planned"),
    Edge("m_ens", "o_forecast", "weather", "Member × lead-day LDZ weather.", status="planned"),
)


def node(node_id: str) -> Node:
    return next(n for n in NODES if n.id == node_id)
