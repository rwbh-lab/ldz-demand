# ldz-demand

LDZ-level Composite Weather Variable (CWV) gas demand models for GB, extended to probabilistic
demand forecasts from the ECMWF ensemble.

> Status: skeleton. Full explainer to be migrated from the original project notes.

## Install

```bash
python -m pip install -e ".[all,dev]"     # or ".[db]" etc. for a subset
python -m pytest
```

MySQL tests start a throwaway `mysql:8.4` container and are skipped if Docker isn't running.

## Layout

```
config/            default.ini (committed), local.ini (gitignored overrides)
docs/
src/ldz_demand/
  config.py        config loading (default.ini + local.ini)
  data/datasets.py processed table definitions (shared by CSV and MySQL)
  data/ingest/     National Gas, ERA5, ECMWF ENS ingestors
  data/store/      Store interface, CSV cache and MySQL implementations
  db/              MySQL connection, DDL, migration runner (python -m ldz_demand.db)
  models/          LDZ network, CWV demand estimator, seasonal normal
db/migrations/     versioned SQL migrations (NNN_description.sql)
tests/
data/              cache/ and raw/ — local only, never committed
```

## Storage modes

Processed tables go through one `Store` interface; `get_store(config)` picks the backend.

- `database = false` (default): CSV files in `data/cache/`. No setup — suits one-off use.
- `database = true`: MySQL (needs the `db` extra). Set in `config/local.ini`.

Raw downloads (National Gas CSVs, ERA5 NetCDF, ECMWF GRIB) always go to `raw_dir` as files, in
their native format, whichever backend is used.

## Database mode (MySQL)

1. Create a MySQL 8 database and a user with full rights on it only.
2. Copy `.env.example` to `.env` and fill in the connection details. `.env` is gitignored.
   - `LDZ_DB_HOST` for a single host, or `LDZ_DB_HOST_LOCAL` / `LDZ_DB_HOST_REMOTE` with
     `LDZ_DB_NETWORK=auto` to use the LAN when reachable and fall back to a remote address
     (e.g. a VPN) otherwise. `LDZ_DB_HOME_GATEWAY` limits the LAN attempt to your home network.
3. Set `database = true` in `config/local.ini`.
4. Create the tables:

```bash
python -m ldz_demand.db status      # connection check + applied / pending migrations
python -m ldz_demand.db migrate     # apply pending migrations (--dry-run to preview)
```

### Migrations

- Schema changes are SQL files in `db/migrations/`, applied in number order and recorded in
  `schema_migrations` with a checksum.
- **Never edit a migration once it has been applied** — add a new one. The runner refuses to run
  if an applied file has changed or been removed, or if two files share a number.
- To add a table: define the `Dataset` in `data/datasets.py`, then draft the SQL with
  `python -m ldz_demand.db draft <dataset>` into the next numbered file. A test checks that the
  migrated tables match the `Dataset` definitions.
- MySQL commits DDL immediately, so a failed migration is not rolled back — keep one change per file.
