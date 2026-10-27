# data

Local data. Everything here is git-ignored except `sample/`.

| Folder | What |
|---|---|
| `raw/` | The download archive: National Gas CSVs, ERA5 NetCDF, ensemble runs cropped to GB. Set `raw_dir` in `config/local.ini` to keep it elsewhere |
| `cache/` | The processed tables as CSV files (the default store; with MySQL they go to the database instead) |
| `results/` | Experiment and backtest outputs (`python -m ldz_demand.models.experiment`) |
| `sample/` | Committed: one ensemble run, its inputs and the actuals, for the [quick start](../docs/user_quickstart.md) |
| `quickstart/` | The quick start's working copy and outputs, rewritten on each run |

Everything in `raw/` can be downloaded again, and everything else rebuilt from it; see the
[user guide](../docs/user_guide.md).
