# User guide — building the data from scratch

How to download the source data, archive it, and build the tables the models use. Everything here
uses free, public data. For *why* the project is built this way, see `methodology.md`; for what the
models found, `results.md`; for each modelling choice and why, `decisions.md`.

Sections marked **🚧 Coming soon** describe parts that are planned but not built yet.

---

## 1. Overview

The pipeline has two stages, and every source follows the same pattern:

```
  ingest                        raw_dir                          build                   Store
  (download + archive)   ──▶    source files, untouched   ──▶    (parse / aggregate) ──▶  tables
```

- **Ingestors** only download and archive. Raw files are never modified or overwritten.
- **Builders** read only the raw archive and write tables. Any table can be rebuilt from the
  archive at any time, without downloading again.
- The **raw archive is the source of truth.** Some sources only keep a rolling window of history
  (National Gas: ~5 years), so your archive will eventually hold data the source no longer has.

Tables are written to a **Store**, in one of two modes:

| Mode | Setting | Where tables go | Setup |
|---|---|---|---|
| CSV (default) | `database = false` | CSV files in `data/cache/` | None |
| MySQL | `database = true` | A MySQL 8 database | A database + user, see §3.4 |

Raw files go to `raw_dir` in both modes.

---

## 2. Prerequisites

- **Python 3.11+** and git
- **Disk space:** ~600 MB for the raw archive (October 2026: National Gas ~20 MB, ERA5 ~530 MB)
- **Accounts:** a free **Copernicus Climate Data Store** account, for ERA5 only. National Gas and
  ECMWF open data need no account.
- **Optional:** a **MySQL 8** server for database mode; **Docker** to run the MySQL tests.

---

## 3. Setup

### 3.1 Install

```bash
git clone <repo-url> ldz-demand && cd ldz-demand
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[all]"
```

`all` installs every optional extra. To install less, pick from:

| Extra | For |
|---|---|
| `weather` | ERA5 / ECMWF downloads (xarray, netCDF, cdsapi, ecmwf-opendata) |
| `db` | MySQL mode (SQLAlchemy, PyMySQL, python-dotenv) |
| `dashboard` | Interactive data pages (Marimo, Plotly) |
| `geo`, `models`, `plot` | LDZ geometry, model fitting, figures |
| `dev` | pytest, ruff (`deploy/ci/check.sh` runs what CI does) |

### 3.2 Local config

Copy the template and edit it. `config/local.ini` is gitignored and only needs the keys you change
from `config/default.ini`.

```bash
cp config/local.ini.example config/local.ini
```

```ini
[storage]
database = false                       ; true for MySQL mode (§3.4)
raw_dir = /path/with/space/for/raw     ; default: data/raw inside the repo
```

Check where raw files will go:

```bash
python -c "from ldz_demand.config import create_config, resolve_path; print(resolve_path(create_config(), 'storage', 'raw_dir'))"
```

### 3.3 Copernicus (ERA5)

1. Register at <https://cds.climate.copernicus.eu> and copy your **API token** from your profile.
2. Create `~/.cdsapirc` in your home folder (not the repo) from the template, and add the token:
   ```bash
   cp config/cdsapirc.example ~/.cdsapirc && chmod 600 ~/.cdsapirc
   ```
3. Accept the licence: open the *ERA5 hourly data on single levels* dataset page → **Download**
   tab → **Terms of use** → **Accept**.

### 3.4 MySQL mode (optional)

1. Create a MySQL 8 database and a user with full rights on that database only.
2. Copy `.env.example` to `.env` (gitignored) and fill in the connection details — see §11.3.
3. Set `database = true` in `config/local.ini`.
4. Check the connection and create the tables:
   ```bash
   python -m ldz_demand.db status     # connects; lists applied / pending migrations
   python -m ldz_demand.db migrate    # creates the tables
   ```

Run `migrate` again whenever you update the code; it only applies new migrations.

---

## 4. Datasets

### 4.1 National Gas — LDZ demand, calorific value, CWV, NTS offtakes, forecasts

| | |
|---|---|
| **What** | Daily demand and weather variables for each of GB's 13 Local Distribution Zones (LDZs) |
| **Source** | National Gas Transmission data portal, <https://data.nationalgas.com> (CSV API) |
| **Account** | None |
| **Terms** | See the portal's terms of use |
| **History** | Rolling ~5 years (earliest gas day on 2026-10-11: 2021-10-12) |
| **Size** | ~20 MB for 5 years per series (~40 MB for forecasts, every issue kept) |
| **Raw files** | `raw_dir/national_gas/<year>/ng_ldz_…csv` (LDZ items), `…/offtakes/<year>/ng_offtakes_…csv`, `…/forecasts/<year>/ng_forecasts_…csv` |

Three series are downloaded:

- **`ldz`** — the per-LDZ items below.
- **`offtakes`** — energy offtaken from the national transmission system (NTS) at each of the 122
  LDZ offtake points (kWh/day). Summed per LDZ, an independent meter of the gas entering it, used to
  check the published totals (§9).
- **`forecasts`** — National Gas's own forecasts per LDZ, **every issue kept**: total LDZ demand
  (`demand_forecast`, mcm) and the forecast CWV (`cwv_forecast_d`, issued on the gas day, and
  `cwv_forecast_d_minus_1`, issued the day before). Demand is issued ~8 times per gas day: on D−1 at
  ~13:00, ~16:00 and ~24:00, and on D at ~10:00, ~13:00, ~16:00, ~21:00 and ~24:00 (UK time). The
  benchmark our forecasts are compared with, issue time for issue time. Like everything on the portal
  only the last ~5 years are kept, so the archive becomes the only copy of the oldest forecasts.

LDZs: EA, EM, NE, NO, NT, NW, SC, SE, SO, SW, WM, WN, WS.

| Item | Unit | Published | Notes |
|---|---|---|---|
| `demand_total_d1` / `_d6` | **mcm** | D+1 / D+6 | Total LDZ demand, metered |
| `demand_dm_d1` / `_d6` | kWh | D+1 / D+6 | Daily-metered sites (large industry and business) |
| `demand_ndm_d1` / `_d6` | kWh | D+1 / D+6 | Non-daily-metered (homes, small business), allocated |
| `demand_uig_d1` / `_d6` | kWh | D+1 / D+6 | Unidentified gas. **Only published from March 2025** |
| `cv` | MJ/m³ | D+1 | LDZ calorific value |
| `cwv_actual` | °C | D+1 | Official Composite Weather Variable |

- **Units differ.** Total demand is a volume (mcm), the others are energy (kWh). To convert:
  `kWh = mcm × 10⁶ × CV / 3.6`.
- **D+1 vs D+6.** D+1 values are provisional, published the day after. D+6 values are closed out
  six days later; use these for modelling. The most recent ~6 days only have D+1 values.
- **Formatting.** Some offtake values are published with thousands separators (`"2,489,711"`); the
  builder handles this.
- **SE total.** SE normally takes ~31 GWh/day from a non-NTS input, which is missing from its
  published total from Sep 2022 to Feb 2024 (and a few short spells since). Detected and flagged
  using the offtakes — see §9.

### 4.2 ERA5 — hourly reanalysis weather

| | |
|---|---|
| **What** | Hourly 2 m temperature and 10 m wind (u, v) on a 0.25° grid over GB; plus (group `extra`) surface solar radiation and total precipitation |
| **Source** | Copernicus Climate Data Store, dataset `reanalysis-era5-single-levels` |
| **Account** | Free CDS account + accepted licence (§3.3) |
| **Attribution** | Required: *"Contains modified Copernicus Climate Change Service information [year]"* |
| **History** | 1940 to ~5 days ago. Default download starts 2021-07 (`[era5] start`) |
| **Area** | 61°N, 8.5°W to 49.5°N, 2°E (`[era5] area`) |
| **Size** | ~9 MB per month |
| **Raw files** | `raw_dir/era5/<year>/era5_gb_YYYY-MM.nc` (final) and `era5t_gb_YYYY-MM_pulled_<UTC time>.nc` (preliminary); the extra group as `era5x_gb_…` / `era5xt_gb_…` |

- **Final vs preliminary.** Recent data is preliminary (*ERA5T*) and is replaced by final ERA5
  about 2–3 months later. Months older than 90 days are downloaded once as final files; more recent
  months are re-downloaded to new preliminary files on each run. The newest file wins when reading.
- **Gas day.** Hourly values are averaged over the UK gas day, 05:00 to 05:00 UK local time. Days
  spanning a clock change are 23 or 25 hours long.
- **Extra variables** (`--group extra`): surface solar radiation downwards and total precipitation,
  in their own monthly files so an existing archive gains them without re-downloading temperature
  and wind. Delivered as hourly accumulations; read as mean W m⁻² and mm over the hour ending at
  each time. Daily minimum / maximum temperature come from the hourly 2 m temperature.

### 4.3 ECMWF ensemble forecasts

| | |
|---|---|
| **Source** | ECMWF open data (`data.ecmwf.int`), IFS ensemble (`enfo`), via the `ecmwf-opendata` client |
| **Licence** | CC-BY-4.0, no account — credit ECMWF |
| **Members** | 50 perturbed members (`pf`, numbers 1–50). The open-data files don't include the control forecast |
| **Variables** | 2 m temperature (`2t`), 10 m wind (`10u`, `10v`), surface solar radiation (`ssrd`), total precipitation (`tp`), and the 2 m temperature minimum / maximum over each step's period (`mn2t3` / `mx2t3` to 144 h, `mn2t6` / `mx2t6` after). Runs archived before 2026-10-13 have temperature and wind only |
| **Run / horizon** | The 00z run, 15 days: 3-hourly to day 6, then 6-hourly (85 steps, `[ecmwf_ens] steps`) |
| **Published** | The whole 00z run is online by about 09:30 UTC; the portal keeps only the last few days |
| **Area** | Cropped to the ERA5 box (`[ecmwf_ens] area`), so forecast and reanalysis grids match cell for cell |
| **Size** | ~23 GB downloaded per run, ~90 MB stored. Three steps download at once (`[ecmwf_ens] downloads`): ~20 minutes on a laptop; the log reports download and decode times |
| **Raw files** | `raw_dir/ecmwf_ens/<year>/ens_gb_YYYYMMDD_00z.nc` |

- **Only GB is kept.** The published files are global, one per step with every variable and member.
  Each step's fields (~270 MB) are downloaded, cropped and the global download deleted at once, so
  disk use never exceeds about one step. Solar radiation and precipitation are accumulated from the
  start of the run; reading a run turns them into mean W m⁻² and mm over each step's period. This is the one raw source not archived exactly as
  downloaded; the run file records what was fetched, from where and when.
- **Resumable.** Finished steps are kept under `raw_dir/ecmwf_ens/partial/` until the run is complete;
  an interrupted run carries on from there next time.
- **History.** ECMWF's cloud mirrors (e.g. `source = aws`) hold older runs (0.25° from about February
  2024). Backfilling from them is planned, for chosen winters only.

---

## 5. Running the pipeline

### 5.1 National Gas

```bash
python -m ldz_demand.data.ingest.national_gas refresh    # download both series -> raw_dir
python -m ldz_demand.data.build.ng_ldz_daily             # raw_dir -> ng_ldz_daily
python -m ldz_demand.data.build.ng_offtake_daily         # raw_dir -> ng_offtake_daily
python -m ldz_demand.data.build.ng_forecast_daily        # raw_dir -> ng_forecast_daily
```

- **First run:** `refresh` downloads the full ~5 years of both series (12 requests, 2–3 minutes).
  The builds then write ~204,000 and ~219,000 rows. In MySQL mode, run `python -m ldz_demand.db
  migrate` first so both tables exist.
- **One series only:** add `--series ldz`, `--series offtakes` or `--series forecasts` to `refresh` / `pull`.
  The first `refresh` of a new series downloads its full ~5-year history.
- **Later runs:** `refresh` starts 10 days before the last archived gas day, so D+6 values that
  were missing get filled in. Rebuild only recent rows with `--since`:
  ```bash
  python -m ldz_demand.data.build.ng_ldz_daily --since 2026-09-01
  ```
- **Explicit range:** `python -m ldz_demand.data.ingest.national_gas pull 2024-01-01 2024-12-31`

### 5.2 ERA5

```bash
python -m ldz_demand.data.ingest.era5 refresh                  # download -> raw_dir (core + extra)
python -m ldz_demand.data.ingest.era5 refresh --group extra    # only solar radiation + precipitation
python -m ldz_demand.data.ingest.era5 pull 2026-01 2026-01     # explicit month range
```

- **Runtime:** one request per month; each takes ~2–4 minutes, mostly queueing and processing on
  the Copernicus side. The default 2021-07 start is ~63 months, so **2–4 hours**. Leave it running;
  if it stops, run it again and it skips months already downloaded.
- Try a single month first to check your account and licence.

**Build:** `weather_ldz_daily`, gas-day temperature and wind per LDZ, for every map method ×
weighting plus the official one-station reference:

```bash
python -m ldz_demand.data.build.weather_ldz_daily                  # every month in the archive
python -m ldz_demand.data.build.weather_ldz_daily --since 2026-08  # that month onwards
```

- Uses the committed cell weights (`ldz_demand/geo/data/ldz_cell_weights.csv`, rebuilt by
  `python -m ldz_demand.geo build`). If you change `[era5] area`, rebuild the weights first.
- Variables per gas day: mean temperature, wind and solar radiation; lowest and highest hourly
  temperature; total precipitation. Solar radiation and precipitation need the ERA5 extra files
  (`refresh --group extra`); rebuild after downloading them.
- Safe to rerun: rows are replaced. Rerun after `refresh` so preliminary (ERA5T) days are replaced by
  final ERA5 once it arrives; the `source` column says which each day is.

**Build:** `weather_ldz_hourly`, the hourly LDZ series behind the daily table, for the
`[ldz_weather] detail_variants` only (default: sampled · gas use and the station reference, ~2.3M rows
for 2021-07 onwards). Kept so ways of averaging a gas day (flat, or weighting the morning and evening
heating peaks) can be tested against demand without going back to the gridded archive:

```bash
python -m ldz_demand.data.build.weather_ldz_hourly                  # every month in the archive
python -m ldz_demand.data.build.weather_ldz_hourly --since 2026-08  # that month onwards
```

### 5.3 ECMWF ensemble

```bash
python -m ldz_demand.data.ingest.ecmwf_ens refresh            # the latest run, plus any missing from the last 3 days
python -m ldz_demand.data.ingest.ecmwf_ens pull 2026-10-12    # one run (only while still on the portal)
python -m ldz_demand.data.ingest.ecmwf_ens status             # archived runs
```

`refresh` exits with an error if the latest run didn't make it into the archive, so a scheduler can
alert on it. Runs only stay on the portal for a few days, so schedule it daily (below).

**Build:** `ens_ldz_daily`, gas-day forecast weather per LDZ for every member and lead day 0–14, with
the same cell weights as `weather_ldz_daily` (detail variants only, ~39,000 rows a run):

```bash
python -m ldz_demand.data.build.ens_ldz_daily                     # runs not built yet
python -m ldz_demand.data.build.ens_ldz_daily --since 2026-10-10  # every run from that date
```

- **Gas-day means from forecast steps.** Steps are 3-hourly to day 6 and 6-hourly after, so a gas day
  has 8 or 4 samples. Method `flat` takes the series as a straight line between steps and averages it
  over the gas day (exact however the steps are spaced). `coverage_h` is the hours of the gas day the
  steps cover: 24 (23 / 25 at the clock changes), and 22 on lead day 14, which ends a few hours
  after the last step.
- **Lead day 0** is the run's own gas day: it started a few hours before the run was published.
- **Solar radiation, precipitation, extremes** describe each step's period: solar radiation is averaged
  over the periods' hours in the gas day, precipitation summed pro rata, and `tmin` / `tmax` taken over
  the periods at least half inside it.
- The gridded runs stay archived, so the table can be rebuilt with another method or variant.

### 5.4 Scheduled jobs (Docker)

Two jobs keep everything current; `ldz_demand/jobs.py` lists their steps (`python -m ldz_demand.jobs
daily --list`):

| Job | When | Steps |
|---|---|---|
| `daily` | daily, after the 00z ensemble is published (~09:30 UTC) | `ecmwf_ens refresh` → `ens_ldz_daily` |
| `weekly` | weekly, e.g. Sunday after that day's daily job | `national_gas refresh` → `ng_ldz_daily`, `ng_offtake_daily`, `ng_forecast_daily` → `era5 refresh` → `weather_ldz_daily --recent 1` → `models.forecast --missing` |

Only the ensemble has to be daily: its runs leave the portal after a few days. National Gas keeps five
years and Copernicus all of ERA5, and the forecasts are made *as issued* (each uses only the ERA5 that
existed on its run date), so a weekly batch makes the same forecasts a daily job would have. Every step
runs even if an earlier one failed (a missing ERA5 week is bridged in the forecasts); the job fails if
any step does, so the scheduler can report it.

**The image.** The `Dockerfile` packages the jobs (with the `weather`, `db` and `forecast` extras). In
the container the config is `config/docker.ini`: the raw archive is mounted at `/data/raw` and tables go
to MySQL, so the jobs need the database settings.

```bash
docker build -t ldz-demand .     # add --platform linux/amd64 to build on Apple silicon for an Intel/AMD host
```

**Running a job.** `deploy/docker/compose.yaml` defines both jobs. Copy `deploy/docker/.env.example` to
`deploy/docker/.env` (git-ignored) and set the paths for this host: `RAW_DIR` (the raw archive), `DB_ENV`
(a file with `LDZ_DB_HOST`, `LDZ_DB_PORT`, `LDZ_DB_NAME`, `LDZ_DB_USER`, `LDZ_DB_PASSWORD`) and, for the
weekly job, `CDS_ENV` (a file with `CDSAPI_URL` and `CDSAPI_KEY`). Keep the two settings files readable
by their owner only. Then:

```bash
docker compose -f deploy/docker/compose.yaml run --rm daily
docker compose -f deploy/docker/compose.yaml run --rm weekly
```

Without Compose, the same with `docker run`:

```bash
docker run --rm -v <raw dir>:/data/raw --env-file <db.env> ldz-demand ldz_demand.jobs daily
docker run --rm -v <raw dir>:/data/raw --env-file <db.env> --env-file <cds.env> ldz-demand ldz_demand.jobs weekly
```

The database host must be reachable from inside a container: usually the server's LAN address rather
than `localhost` or a VPN-only address. Migration 007 (`demand_forecast_daily`) must be applied
(`python -m ldz_demand.db migrate`).

**Scheduling.** Use whatever the host has; the job is one command either way. For example:

- **cron** (Linux):
  ```
  0 11 * * *  cd /path/to/ldz-demand && docker compose -f deploy/docker/compose.yaml run --rm daily  >> logs/daily.log 2>&1
  0 12 * * 0  cd /path/to/ldz-demand && docker compose -f deploy/docker/compose.yaml run --rm weekly >> logs/weekly.log 2>&1
  ```
- **macOS:** a launchd agent running the same commands (`StartCalendarInterval`).
- **A NAS** (Synology, QNAP, …): its task scheduler, running the `docker run` form as a user allowed to
  use Docker, with email on failure if it offers it.
- **Without Docker:** the same jobs run directly, `python -m ldz_demand.jobs daily`, with the
  `weather,db,forecast` extras installed and `config/local.ini` pointing at the archive and the database.

Archive contents at any time:
`docker run --rm -v <raw dir>:/data/raw ldz-demand ldz_demand.data.ingest.ecmwf_ens status`.

---

## 6. What gets built

### 6.1 Raw archive

```
raw_dir/
├── national_gas/
│   ├── <year>/ng_ldz_<start>_<end>_pulled_<UTC time>.csv     one file per request, never overwritten
│   ├── offtakes/<year>/ng_offtakes_<start>_<end>_pulled_<UTC time>.csv
│   └── forecasts/<year>/ng_forecasts_<start>_<end>_pulled_<UTC time>.csv
├── era5/
│   └── <year>/era5_gb_YYYY-MM.nc                            final month
│       <year>/era5t_gb_YYYY-MM_pulled_<UTC time>.nc         preliminary month, one per download
│       <year>/era5x_gb_YYYY-MM.nc, era5xt_gb_…              the same for the extra variables
└── ecmwf_ens/
    ├── <year>/ens_gb_YYYYMMDD_00z.nc                        one ensemble run, cropped to GB
    └── partial/YYYYMMDD_00z/step_NNN.nc                     steps of a run still downloading
```

### 6.2 Tables

**`ng_ldz_daily`** — long format, one row per gas day × LDZ × item. Key: `(gas_day, ldz, item)`.

| Column | Type | Notes |
|---|---|---|
| `gas_day` | date | Applicable gas day |
| `ldz` | text | EA … WS |
| `item` | text | See §4.1 |
| `data_item_id` | text | National Gas ID (PUBOB…) |
| `value` | float | |
| `unit` | text | `mcm`, `kWh`, `MJ/m3`, `degC` — check before combining items |
| `quality` | text | Portal quality indicator |
| `applicable_at` | datetime | When the value was published |
| `generated_time` | datetime | |

**`ng_offtake_daily`** — one row per gas day × LDZ × offtake site. Key: `(gas_day, ldz, site)`.
Same columns as `ng_ldz_daily`, with `site` (e.g. `Farningham`) in place of `item`; `unit` is
always `kWh`.

**`ng_forecast_daily`** — National Gas forecasts, one row per gas day × LDZ × item × issue.
Key: `(gas_day, ldz, item, issued_at)`. `issued_at` is when the issue was made (UK time); `issue_day`
is its calendar date minus the gas day (−1 day ahead, 0 within day). Other columns as `ng_ldz_daily`.

**`weather_ldz_daily`** — one row per gas day × LDZ × variant × variable.
Key: `(gas_day, ldz, membership, weighting, variable)`.

| Column | Type | Notes |
|---|---|---|
| `gas_day` | date | 05:00–05:00 UK time |
| `ldz` | str | |
| `membership` | str | `authority`, `voronoi`, `hybrid`, `sampled` (map methods), or `station` |
| `weighting` | str | `area`, `gas` (DESNZ gas use), or `point` (station) |
| `variable` | str | `t2m` (2 m temperature, mean), `t2m_heat` (2 m temperature weighted to the heating hours — 06–09 and 16–22 double, 23–05 half; the demand model's temperature), `ws10` (10 m wind speed, mean), `tmin` / `tmax` (lowest / highest hourly temperature), `ssrd` (surface solar radiation, mean), `tp` (precipitation, total) |
| `value` | float | gas-day value: mean, minimum / maximum or total, by variable |
| `unit` | str | `degC`, `m s-1`, `W m-2`, `mm` |
| `source` | str | `era5` (final) or `era5t` (preliminary) |

**`weather_ldz_hourly`** — the hourly series behind `weather_ldz_daily`, detail variants only.
Key: `(time, ldz, membership, weighting, variable)`; `time` is the ERA5 hour (UTC). Variables `t2m`,
`ws10` at the hour; `ssrd` (mean W m⁻²) and `tp` (mm) over the hour ending then. Other columns as
`weather_ldz_daily`.

**`ens_ldz_daily`** — one row per run × member × gas day × LDZ × variant × variable × method.
Key: `(run_date, run_hour, member, gas_day, ldz, membership, weighting, variable, method)`.

| Column | Type | Notes |
|---|---|---|
| `run_date`, `run_hour` | date, int | The forecast run (00z) |
| `member` | int | 1–50 |
| `gas_day`, `lead_days` | date, int | `lead_days = gas_day − run_date`, 0–14 |
| `ldz`, `membership`, `weighting`, `variable` | str | As `weather_ldz_daily` (detail variants) |
| `variable` | str | As `weather_ldz_daily`: `t2m`, `t2m_heat` (from the hourly instants, interpolated between steps), `ws10`, `tmin`, `tmax`, `ssrd`, `tp` (runs archived before 2026-10-13: `t2m`, `t2m_heat`, `ws10` only) |
| `method` | str | Gas-day averaging for `t2m` / `ws10`: `flat` |
| `value`, `unit` | float, str | |
| `coverage_h` | float | Hours of the gas day the forecast steps cover |

---

## 7. Keeping it up to date

| Source | How often | Why |
|---|---|---|
| National Gas | Weekly (or daily) | D+6 values close out a week behind; the 10-day lookback fills them in |
| ERA5 | Monthly | Preliminary months are replaced by final data after ~3 months |
| ECMWF ensemble | **Daily** | Runs leave the portal after a few days (§5.4: the daily job) |

**Back up `raw_dir`.** For National Gas it will become the only copy of the oldest years.

---

## 8. Rebuilding from the archive

Builders read only `raw_dir`, so tables can always be rebuilt without downloading:

```bash
python -m ldz_demand.data.build.ng_ldz_daily
python -m ldz_demand.data.build.ng_offtake_daily
```

Builds overwrite matching rows, so running one twice is safe. To start completely clean, delete the
table first: in CSV mode remove `data/cache/ng_ldz_daily.csv`; in MySQL mode empty the table
(`TRUNCATE ng_ldz_daily`).

---

## 9. Checking the data

- **Dashboard.** An interactive page walks through the National Gas data — coverage, demand
  composition, whether the parts add up (with flagged days), and weather vs demand:
  ```bash
  marimo run dashboard/ng_ldz_daily.py
  ```
  It reads from the Store, so it works in CSV or MySQL mode. A second page maps hourly ERA5
  temperature and wind over GB for a few notable gas days (reads the raw files in `raw_dir`):
  ```bash
  marimo run dashboard/era5_weather.py
  ```
  Model pages: *LDZ geography* (the LDZ map methods and the demand check) and *LDZ weather* (how
  much LDZ temperature and wind depend on the map method and weighting; reads `weather_ldz_daily`).
  **All pages together**, opening on an overview page written like a paper, with the contents
  (Data / Models) at the head of every page to move between them:
  ```bash
  python -m ldz_demand.dashboard            # http://localhost:2718
  ```
  Each page loads its data when first opened (a few seconds), then stays responsive. On start-up, any
  built ensemble run without a demand forecast gets one first (a 1 s check when
  there is none), so the Live forecasts page shows the latest run; `--no-forecast` skips it.

  **The hosted snapshot** ([rwbh-lab.github.io/ldz-demand](https://rwbh-lab.github.io/ldz-demand/)) is the
  same pages run once against the local data and saved with their outputs: charts keep hover and zoom,
  marimo's controls stay at their defaults, and each page says what date its data runs to. To refresh it
  (e.g. after the weekly job; the ERA5 page needs the raw archive, so mount the share first):
  ```bash
  python -m ldz_demand.publish          # build into deploy/site/ (~2 min) to look at first
  python -m ldz_demand.publish --push   # build and replace the gh-pages branch on the `github` remote
  ```
  A page that shows a local path or a private address (usually one that couldn't find its data) stops the
  build rather than being published. Once, on GitHub: Settings → Pages → Deploy from a branch →
  `gh-pages`, `/ (root)`.
  Theme: `python -m ldz_demand.charts.style
  <claude_dark | neutral_dark | light>`, and set `[tool.marimo.display] theme` in `pyproject.toml` to
  match (`dark` / `light`). More pages 🚧 coming soon.
- **Coverage.** The National Gas build logs gaps inside each series' date range. No warning means
  every series is complete from its first to its last day.
- **Flags.** `ldz_demand.data.ldz_energy.energy_frame()` converts everything to GWh/day and flags
  each LDZ-day: **invalid** (total < 10% of DM + NDM), **missing feed** (an LDZ's usual non-NTS
  input — total minus offtakes — has dropped out of the published total; SE 2022–24), **mismatch**
  (total minus offtakes far from its usual level). It also gives two model targets: `target`
  (total − DM, flagged days excluded) and `target_repaired` (missing-feed days repaired as
  offtakes + usual input). Without offtake data, a simpler rule flags totals < 70% of DM + NDM.
- **Energy balance.** Total demand converted to energy should roughly match DM + NDM + UIG. The
  difference is mostly LDZ shrinkage (leakage and own use): a fairly constant amount of energy, so
  ~0.3% of demand in winter but ~1.5% in summer when demand is low (SE, 2025–26). A few days are
  far off — data errors at source; check before using summer days. UIG only exists from March 2025.

```python
from ldz_demand.config import create_config
from ldz_demand.data.datasets import NG_LDZ_DAILY
from ldz_demand.data.store import get_store

df = get_store(create_config()).read(NG_LDZ_DAILY, start="2026-01-01", ldz="SE")
w = df.pivot_table(index="gas_day", columns="item", values="value")
total_kwh = w["demand_total_d6"] * 1e6 * w["cv"] / 3.6
parts = w["demand_dm_d6"] + w["demand_ndm_d6"] + w["demand_uig_d6"]
print((100 * (total_kwh - parts) / total_kwh).describe())   # SE 2026: mean ~1%, winter ~0.3%
```

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| CDS `403 ... required licences not accepted` | Accept the ERA5 licence on the dataset page (§3.3) |
| CDS authentication errors | `~/.cdsapirc` key must be the token only — no `UID:` prefix |
| ERA5 very slow | Normal: requests queue on the Copernicus side. Leave it running |
| Raw files appear in `data/raw/` unexpectedly | `raw_dir` isn't set in `config/local.ini` (§3.2) |
| `Database config error: LDZ_DB_... is not set` | Missing value in `.env` (§11.3) |
| MySQL `Can't connect` | Host/port wrong or not reachable; `python -m ldz_demand.db status` shows which host it tried |
| `database = true needs the db extra` | `python -m pip install -e ".[db]"` |
| `Applied migrations were edited` | A migration file changed after it was applied. Restore it and add a new migration instead |

---

## 11. Reference

### 11.1 Commands

| Command | Does |
|---|---|
| `python -m ldz_demand.data.ingest.national_gas refresh [--series ldz\|offtakes\|forecasts]` | Download new National Gas days (full history if none archived) |
| `python -m ldz_demand.data.ingest.national_gas pull START END [--series …]` | Download a gas-day range (YYYY-MM-DD) |
| `python -m ldz_demand.data.build.ng_ldz_daily [--since DAY]` | Build `ng_ldz_daily` from the archive |
| `python -m ldz_demand.data.build.ng_offtake_daily [--since DAY]` | Build `ng_offtake_daily` from the archive |
| `python -m ldz_demand.data.build.ng_forecast_daily [--since DAY]` | Build `ng_forecast_daily` from the archive |
| `python -m ldz_demand.data.ingest.era5 refresh` | Download ERA5 from `[era5] start` to the latest month |
| `python -m ldz_demand.data.ingest.era5 pull FIRST LAST` | Download a month range (YYYY-MM) |
| `python -m ldz_demand.data.ingest.ecmwf_ens refresh` | Archive the latest ensemble run(s) not yet archived |
| `python -m ldz_demand.data.ingest.ecmwf_ens pull DATE` | Archive one ensemble run (YYYY-MM-DD) |
| `python -m ldz_demand.data.ingest.ecmwf_ens status` | List archived ensemble runs |
| `python -m ldz_demand.data.build.weather_ldz_daily [--since MONTH \| --recent N]` | Build `weather_ldz_daily` from ERA5 (`--recent 1`: this month and last) |
| `python -m ldz_demand.data.build.weather_ldz_hourly [--since MONTH]` | Build `weather_ldz_hourly` from ERA5 |
| `python -m ldz_demand.data.build.ens_ldz_daily [--since DATE]` | Build `ens_ldz_daily` from the ensemble archive |
| `python -m ldz_demand.models.experiment <name> [--ldz …]` | Run a model experiment (cwv_inputs, variables, seasonal, change, averaging, target, final) → `data/results/` (see `results.md`) |
| `python -m ldz_demand.models.fit` | Fit the final model on every usable day → `models/data/final_fit.csv` |
| `python -m ldz_demand.models.results` | Export the compact results bundle for the dashboard → `models/data/results/` |
| `python -m ldz_demand.models.forecast DATE… \| --missing` | Demand forecasts from ensemble runs → `demand_forecast_daily` |
| `python -m ldz_demand.dashboard` | Serve all dashboard pages (overview at /), forecasting new ensemble runs first |
| `python -m ldz_demand.jobs daily \| weekly [--list]` | The scheduled jobs (§5.4); usually run in the Docker image |
| `python -m ldz_demand.db status` | MySQL: connection check + migration status |
| `python -m ldz_demand.db migrate [--dry-run]` | MySQL: apply pending migrations |
| `python -m ldz_demand.db draft DATASET` | Print a `CREATE TABLE` for a dataset (developers) |
| `marimo run dashboard/ng_ldz_daily.py` | Open the National Gas data page |
| `marimo run dashboard/era5_weather.py` | Open the ERA5 weather maps page |
| `python -m ldz_demand.charts.style THEME` | Set the dashboard/chart theme |

### 11.2 Config (`config/default.ini`, overridden by `config/local.ini`)

| Section | Key | Default | Meaning |
|---|---|---|---|
| `storage` | `database` | `false` | `true` = MySQL, `false` = CSV |
| `storage` | `cache_dir` | `data/cache` | CSV table location |
| `storage` | `raw_dir` | `data/raw` | Raw archive location |
| `era5` | `start` | `2021-07` | First ERA5 month (three months of warm-up before the demand history) |
| `era5` | `area` | `61, -8.5, 49.5, 2.0` | North, west, south, east (degrees) |
| `ecmwf_ens` | `source` | `ecmwf` | `ecmwf` (open-data portal) or a mirror: `aws`, `azure`, `google` |
| `ecmwf_ens` | `run_hour` | `0` | Forecast run (UTC hour) |
| `ecmwf_ens` | `steps` | `0-144/3,150-360/6` | Forecast hours to download |
| `ecmwf_ens` | `area` | the `[era5]` area | Crop box |
| `ecmwf_ens` | `days_back` | `3` | `refresh` also fetches missing runs this many days back (`1` in the container) |
| `ecmwf_ens` | `downloads` | `3` | Steps downloading at once |
| `ldz_weather` | `detail_variants` | `sampled/gas, station/point` | Variants built hourly / per ensemble member |

Relative paths are relative to the repo root. Set `LDZ_DEMAND_CONFIG` to use a different override
file instead of `config/local.ini`.

### 11.3 Environment (`.env`, MySQL mode)

| Variable | Meaning |
|---|---|
| `LDZ_DB_HOST` | Single host. If set, always used |
| `LDZ_DB_HOST_LOCAL` / `LDZ_DB_HOST_REMOTE` | Two hosts, e.g. a LAN address and one reachable from anywhere |
| `LDZ_DB_NETWORK` | `auto` (default: LOCAL if reachable, else REMOTE), `local` or `remote` |
| `LDZ_DB_HOME_GATEWAY` | Optional: only try LOCAL when your network's gateway matches this |
| `LDZ_DB_PORT` | Default 3306 |
| `LDZ_DB_NAME`, `LDZ_DB_USER`, `LDZ_DB_PASSWORD` | Database and credentials |
