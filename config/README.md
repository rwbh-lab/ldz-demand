# config

Settings, as INI files. `default.ini` is read first, then one override file on top of it.

| File | Use |
|---|---|
| `default.ini` | Committed defaults: CSV storage in `data/`, the ERA5 and ensemble areas, download settings |
| `local.ini` | Your overrides (git-ignored). Copy `local.ini.example`; only the keys you change are needed |
| `docker.ini` | The override inside the Docker image (raw archive at `/data/raw`, MySQL) |
| `quickstart.ini` | Points the dashboard at the quick start's output (`data/quickstart/`) |
| `cdsapirc.example` | Template for `~/.cdsapirc`, the Copernicus key that ERA5 downloads need |

Set `LDZ_DEMAND_CONFIG` to use another override file in place of `local.ini`, e.g.
`LDZ_DEMAND_CONFIG=config/quickstart.ini`. Database credentials go in `.env`, not here (see `.env.example`).
