# User guide — building the data from scratch

How to download the source data, archive it, and build the tables the models use. Everything here
uses free, public data. For *why* the project is built this way, see `methodology.md`.

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
| `dev` | pytest |

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

### 4.1 National Gas — LDZ demand, calorific value, CWV, NTS offtakes

| | |
|---|---|
| **What** | Daily demand and weather variables for each of GB's 13 Local Distribution Zones (LDZs) |
| **Source** | National Gas Transmission data portal, <https://data.nationalgas.com> (CSV API) |
| **Account** | None |
| **Terms** | See the portal's terms of use |
| **History** | Rolling ~5 years (earliest gas day on 2026-10-11: 2021-10-12) |
| **Size** | ~20 MB for 5 years per series |
| **Raw files** | `raw_dir/national_gas/<year>/ng_ldz_…csv` (LDZ items), `raw_dir/national_gas/offtakes/<year>/ng_offtakes_…csv` (offtakes) |

Two series are downloaded:

- **`ldz`** — the per-LDZ items below.
- **`offtakes`** — energy offtaken from the national transmission system (NTS) at each of the 122
  LDZ offtake points (kWh/day). Summed per LDZ, an independent meter of the gas entering it, used to
  check the published totals (§9).

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
| **What** | Hourly 2 m temperature and 10 m wind (u, v) on a 0.25° grid over GB |
| **Source** | Copernicus Climate Data Store, dataset `reanalysis-era5-single-levels` |
| **Account** | Free CDS account + accepted licence (§3.3) |
| **Attribution** | Required: *"Contains modified Copernicus Climate Change Service information [year]"* |
| **History** | 1940 to ~5 days ago. Default download starts 2021-09 (`[era5] start`) |
| **Area** | 61°N, 8.5°W to 49.5°N, 2°E (`[era5] area`) |
| **Size** | ~9 MB per month |
| **Raw files** | `raw_dir/era5/<year>/era5_gb_YYYY-MM.nc` (final) and `era5t_gb_YYYY-MM_pulled_<UTC time>.nc` (preliminary) |

- **Final vs preliminary.** Recent data is preliminary (*ERA5T*) and is replaced by final ERA5
  about 2–3 months later. Months older than 90 days are downloaded once as final files; more recent
  months are re-downloaded to new preliminary files on each run. The newest file wins when reading.
- **Gas day.** Hourly values are averaged over the UK gas day, 05:00 to 05:00 UK local time. Days
  spanning a clock change are 23 or 25 hours long.

### 4.3 ECMWF ensemble forecasts — 🚧 Coming soon

ECMWF open data: the ensemble (control + 50 members), 2 m temperature and 10 m wind, 15-day
horizon. No account; CC-BY-4.0. Only recent runs stay online, so each run used is archived.

---

## 5. Running the pipeline

### 5.1 National Gas

```bash
python -m ldz_demand.data.ingest.national_gas refresh    # download both series -> raw_dir
python -m ldz_demand.data.build.ng_ldz_daily             # raw_dir -> ng_ldz_daily
python -m ldz_demand.data.build.ng_offtake_daily         # raw_dir -> ng_offtake_daily
```

- **First run:** `refresh` downloads the full ~5 years of both series (12 requests, 2–3 minutes).
  The builds then write ~204,000 and ~219,000 rows. In MySQL mode, run `python -m ldz_demand.db
  migrate` first so both tables exist.
- **One series only:** add `--series ldz` or `--series offtakes` to `refresh` / `pull`.
- **Later runs:** `refresh` starts 10 days before the last archived gas day, so D+6 values that
  were missing get filled in. Rebuild only recent rows with `--since`:
  ```bash
  python -m ldz_demand.data.build.ng_ldz_daily --since 2026-09-01
  ```
- **Explicit range:** `python -m ldz_demand.data.ingest.national_gas pull 2024-01-01 2024-12-31`

### 5.2 ERA5

```bash
python -m ldz_demand.data.ingest.era5 refresh            # download -> raw_dir
python -m ldz_demand.data.ingest.era5 pull 2026-01 2026-01   # explicit month range
```

- **Runtime:** one request per month; each takes ~2–4 minutes, mostly queueing and processing on
  the Copernicus side. The default 2021-09 start is ~60 months, so **2–4 hours**. Leave it running;
  if it stops, run it again and it skips months already downloaded.
- Try a single month first to check your account and licence.

**Build — 🚧 Coming soon:** `weather_ldz_daily`, LDZ-weighted gas-day temperature and wind
(needs the LDZ weighting, not built yet).

### 5.3 ECMWF ensemble — 🚧 Coming soon

Ingestor (download + archive each run) and builder (`ens_ldz_daily`) planned. See §4.3 for the data.

---

## 6. What gets built

### 6.1 Raw archive

```
raw_dir/
├── national_gas/
│   ├── <year>/ng_ldz_<start>_<end>_pulled_<UTC time>.csv     one file per request, never overwritten
│   └── offtakes/<year>/ng_offtakes_<start>_<end>_pulled_<UTC time>.csv
└── era5/
    └── <year>/era5_gb_YYYY-MM.nc                            final month
        <year>/era5t_gb_YYYY-MM_pulled_<UTC time>.nc         preliminary month, one per download
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

**🚧 Coming soon**

| Table | Contents |
|---|---|
| `weather_ldz_daily` | ERA5 gas-day temperature and wind per LDZ |
| `ens_ldz_daily` | Ensemble forecast temperature and wind per LDZ, per member and run |

---

## 7. Keeping it up to date

| Source | How often | Why |
|---|---|---|
| National Gas | Weekly (or daily) | D+6 values close out a week behind; the 10-day lookback fills them in |
| ERA5 | Monthly | Preliminary months are replaced by final data after ~3 months |

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
  It reads from the Store, so it works in CSV or MySQL mode. Theme: `python -m ldz_demand.charts.style
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
| `python -m ldz_demand.data.ingest.national_gas refresh [--series ldz\|offtakes]` | Download new National Gas days (full history if none archived) |
| `python -m ldz_demand.data.ingest.national_gas pull START END [--series …]` | Download a gas-day range (YYYY-MM-DD) |
| `python -m ldz_demand.data.build.ng_ldz_daily [--since DAY]` | Build `ng_ldz_daily` from the archive |
| `python -m ldz_demand.data.build.ng_offtake_daily [--since DAY]` | Build `ng_offtake_daily` from the archive |
| `python -m ldz_demand.data.ingest.era5 refresh` | Download ERA5 from `[era5] start` to the latest month |
| `python -m ldz_demand.data.ingest.era5 pull FIRST LAST` | Download a month range (YYYY-MM) |
| `python -m ldz_demand.db status` | MySQL: connection check + migration status |
| `python -m ldz_demand.db migrate [--dry-run]` | MySQL: apply pending migrations |
| `python -m ldz_demand.db draft DATASET` | Print a `CREATE TABLE` for a dataset (developers) |
| `marimo run dashboard/ng_ldz_daily.py` | Open the National Gas data page |
| `python -m ldz_demand.charts.style THEME` | Set the dashboard/chart theme |

### 11.2 Config (`config/default.ini`, overridden by `config/local.ini`)

| Section | Key | Default | Meaning |
|---|---|---|---|
| `storage` | `database` | `false` | `true` = MySQL, `false` = CSV |
| `storage` | `cache_dir` | `data/cache` | CSV table location |
| `storage` | `raw_dir` | `data/raw` | Raw archive location |
| `era5` | `start` | `2021-09` | First ERA5 month |
| `era5` | `area` | `61, -8.5, 49.5, 2.0` | North, west, south, east (degrees) |

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
