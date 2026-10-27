"""
Serve every dashboard page from one local server, with the overview page at /.

    python -m ldz_demand.dashboard              # http://localhost:2718
    python -m ldz_demand.dashboard --port 8080
    python -m ldz_demand.dashboard --no-forecast  # skip making forecasts for new ensemble runs on start-up

On start-up, any built ensemble run without a demand forecast gets one first (as the daily job would),
so the Live forecasts page shows the latest run.
"""

import argparse
import logging
import sys

from ldz_demand.charts.pages import INDEX, PAGES
from ldz_demand.config import get_project_root


def build_app():
    import marimo

    folder = get_project_root() / "dashboard"
    builder = marimo.create_asgi_app()
    for file, page in PAGES.items():
        builder = builder.with_app(path=page.path, root=str(folder / file))
    return builder.with_app(path="/", root=str(folder / INDEX)).build()


def forecast_new_runs() -> None:
    """Forecast every built ensemble run that has no stored forecast; never stops the dashboard starting.

    Only looks for them when the latest built run is newer than the latest forecast (two indexed MAX queries),
    so start-up stays fast when there is nothing new.
    """
    from ldz_demand.config import create_config
    from ldz_demand.data.datasets import DEMAND_FORECAST_DAILY, ENS_LDZ_DAILY
    from ldz_demand.data.store import get_store
    from ldz_demand.models import forecast

    try:
        store = get_store(create_config())
        latest_run, latest_forecast = store.last_date(ENS_LDZ_DAILY), store.last_date(DEMAND_FORECAST_DAILY)
        if latest_run is None or (latest_forecast is not None and latest_run <= latest_forecast):
            return
        runs = forecast.missing_runs(store)
        if runs:
            print(f"Forecasting {len(runs)} new ensemble run(s): {', '.join(runs)} ...")
            forecast.main(runs)
    except Exception as exc:  # e.g. database unreachable, or no ensemble runs built
        logging.getLogger(__name__).warning(f"New forecasts skipped ({exc.__class__.__name__}: {str(exc)[:120]})")


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(prog="python -m ldz_demand.dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2718)
    parser.add_argument("--no-forecast", action="store_true", help="don't forecast new ensemble runs first")
    args = parser.parse_args(argv)
    if not args.no_forecast:
        forecast_new_runs()
    print(f"LDZ demand dashboard: http://{args.host}:{args.port}")
    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
