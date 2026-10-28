# dashboard

The dashboard's pages, one [marimo](https://marimo.io) notebook each. They are plain Python files with
no stored outputs, so they diff like code. `index.py` is the Overview (the landing page) and `summary.py` the full summary; the charts they draw live in
`src/ldz_demand/charts/`.

```bash
python -m ldz_demand.dashboard           # every page from one server: http://localhost:2718
marimo run dashboard/live_forecasts.py   # one page
marimo edit dashboard/live_forecasts.py  # edit one
```

`theme.css` is generated (`python -m ldz_demand.charts.style <theme>`), so don't edit it by hand. The
hosted copy is a static snapshot of these pages (`python -m ldz_demand.publish`).
