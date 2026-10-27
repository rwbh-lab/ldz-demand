# Quick start

Run the final model on a real ensemble forecast in a few minutes, with no data download, model
training, keys or database. Then, optionally, run it on today's forecast.

For everything else (the full archive, refitting, the scheduled jobs, MySQL) see the
[user guide](user_guide.md).

## 1. Install

Python 3.12. The `forecast` and `dashboard` extras are enough for the model and the Live forecasts page.

```bash
git clone https://github.com/rwbh-lab/ldz-demand.git && cd ldz-demand
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[forecast,dashboard]"
```

## 2. Forecast the sample run

```bash
python -m ldz_demand.quickstart
```

The sample is the ECMWF ensemble run of **5 January 2025**, issued three days before the coldest spell
of that winter (8–11 January). It is in `data/sample/`, already turned into gas-day weather for each LDZ,
with the 60 days of ERA5 before it that the model's effective temperature needs and National Gas's
actuals for the fortnight it covers. The fitted model ships with the package.

Each of the 50 members goes through the model for each of the 13 LDZs. The model's own out-of-sample
errors are then added, so the range covers the model as well as the weather. The forecast is made as
issued: like a live forecast, it can't use the last few days of ERA5 before the run (ERA5 is published
about five days late), so those days are bridged.

## 3. The results

The command prints the GB forecast for each day next to what happened:

```
            lead_days     p10     p50     p90  actual  in P10-P90
gas_day
2025-01-05          0  1771.0  1854.0  1943.0  2042.0       False
2025-01-06          1  2076.0  2186.0  2315.0  2156.0        True
2025-01-07          2  2224.0  2336.0  2464.0  2357.0        True
2025-01-08          3  2371.0  2490.0  2605.0  2633.0       False
2025-01-09          4  2498.0  2613.0  2751.0  2608.0        True
2025-01-10          5  2461.0  2592.0  2721.0  2747.0       False
2025-01-11          6  2049.0  2411.0  2622.0  2574.0        True
2025-01-12          7  1706.0  2301.0  2579.0  2356.0        True
2025-01-13          8  1614.0  2225.0  2591.0  2225.0        True
2025-01-14          9  1533.0  2050.0  2534.0  1863.0        True
2025-01-15         10  1597.0  2082.0  2482.0  1715.0        True
2025-01-16         11  1660.0  2081.0  2454.0  1913.0        True
2025-01-17         12  1722.0  2083.0  2422.0  1936.0        True
2025-01-18         13  1661.0  2006.0  2376.0  2046.0        True
```

Five days ahead, the run sees the cold spell coming: demand rising by about 750 GWh/day to a peak on
9–10 January, then the range widening sharply as the members disagree about the thaw. Ten of the 14 days
fall inside P10–P90, which should catch about 80%. The two misses at the peak are just above P90. Lead
day 0 is the weakest, and that comes from the sample, not the model. It has no earlier runs to bridge the
missing ERA5 days with, so it carries 30 December (8 °C) forward over 31 December – 4 January, when it
was really about 1 °C. The effective temperature, which remembers the previous days, starts too warm. A
live forecast bridges with the previous days' ensemble runs instead.

Everything is in `data/quickstart/` (git-ignored, rewritten on each run):

| File | What |
|---|---|
| `demand_2025-01-05_summary.csv` | Per LDZ and GB, per day: mean, P05–P95, the weather-only P10 / P90 |
| `demand_2025-01-05_members.csv` | Every member's demand path |
| `demand_forecast_daily.csv` | The same statistics as the table the dashboard reads |

Demand is the model's target: total LDZ demand less the directly connected (DM) sites, in GWh/day.

## 4. See them on the dashboard

```bash
LDZ_DEMAND_CONFIG=config/quickstart.ini marimo run dashboard/live_forecasts.py
```

`config/quickstart.ini` points the page at `data/quickstart/`. The page shows the forecast fan against
the actuals, for GB or any LDZ, and the verification table.

## 5. Optional: today's forecast

This downloads real data, so it takes longer: about half an hour, mostly the ensemble download (about
23 GB, of which about 100 MB is kept). The ensemble and National Gas need no account. ERA5 needs a free
Copernicus CDS key.

**Set up**

```bash
python -m pip install -e ".[forecast,dashboard,weather]"
```

Get a CDS key (register at cds.climate.copernicus.eu, then accept the ERA5 single-levels licence) and put
it in `~/.cdsapirc` as in `config/cdsapirc.example`.

**Download and build.** Replace the dates: ERA5 from about three months back, and National Gas from two
months back to yesterday.

```bash
python -m ldz_demand.data.ingest.ecmwf_ens refresh        # the latest ensemble run
python -m ldz_demand.data.build.ens_ldz_daily
python -m ldz_demand.data.ingest.era5 pull 2026-08 2026-10
python -m ldz_demand.data.build.weather_ldz_daily
python -m ldz_demand.data.ingest.national_gas pull 2026-08-27 2026-10-26
python -m ldz_demand.data.build.ng_ldz_daily
python -m ldz_demand.data.build.ng_offtake_daily
```

**Forecast and view**

```bash
python -m ldz_demand.models.forecast --missing
marimo run dashboard/live_forecasts.py
```

These use the default store: CSV files in `data/cache/`, with downloads archived in `data/raw/`.

That's the model run on your own data. Going further (the full history, refitting the model,
backtests, the other dashboard pages) is the [user guide](user_guide.md).
