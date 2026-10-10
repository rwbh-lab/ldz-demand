# ldz-demand

LDZ-level Composite Weather Variable (CWV) gas demand models for GB, extended to probabilistic
demand forecasts from the ECMWF ensemble.

> Status: skeleton. Full explainer to be migrated from the original project notes.

## Install

```bash
pip install -e ".[all,dev]"
```

## Layout

```
config/            default.ini (committed), local.ini (gitignored overrides)
docs/
src/ldz_demand/
  config.py        config loading (default.ini + local.ini)
  data/ingest/     National Gas, ERA5, ECMWF ENS ingestors
  data/store/      storage interface + CSV cache implementation
  models/          LDZ network, CWV demand estimator, seasonal normal
tests/
data/              cache/ and raw/ — local only, never committed
```

## Storage modes

- `database = false` (default): processed series are written as CSV to `data/cache/`.
- `database = true`: a database-backed store is injected by the caller. This package never
  depends on a database implementation itself.

Raw gridded downloads (ERA5 NetCDF, ECMWF GRIB) are kept in `data/raw/` in their native format.
