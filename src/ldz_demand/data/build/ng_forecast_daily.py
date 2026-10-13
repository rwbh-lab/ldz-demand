"""
Builds ng_forecast_daily from the archived National Gas forecast responses.

National Gas's own forecasts per LDZ, every issue kept: total LDZ demand (mcm, ~8 issues per gas day,
from the afternoon of D-1 to the end of D) and the forecast CWV (issued on D-1 and on D). These are the
benchmark for our forecasts: compare by issue time, so neither side uses later information.
Same rules as ng_ldz_daily: newest pull with a value wins; rows written with replace.

Run as a script:
    python -m ldz_demand.data.build.ng_forecast_daily [--since 2026-09-01]
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from ldz_demand.config import create_config, resolve_path
from ldz_demand.data.build.ng_ldz_daily import common_columns, latest_values, read_portal_csv
from ldz_demand.data.datasets import NG_FORECAST_DAILY
from ldz_demand.data.ingest.national_gas import NationalGasError, archived_pulls, identify_forecast
from ldz_demand.data.store import Store, get_store

logger = logging.getLogger(__name__)


class NGForecastDailyBuilder:
    """
    Parameters
    ----------
    store : Store
        Destination for NG_FORECAST_DAILY.
    raw_dir : Path
        Raw archive root (forecast files are under raw_dir/national_gas/forecasts).
    """

    def __init__(self, store: Store, raw_dir: Path) -> None:
        self.store = store
        self.raw_dir = Path(raw_dir)

    def build(self, since: date | None = None) -> int:
        pulls = [p for p in archived_pulls(self.raw_dir, "forecasts") if since is None or p.end >= since]
        if not pulls:
            logger.warning(f"No archived forecast pulls under {self.raw_dir / 'national_gas' / 'forecasts'}")
            return 0

        frames = [parse(p.path.read_bytes()).assign(_pulled=p.pulled) for p in pulls]
        df = latest_values(pd.concat(frames, ignore_index=True), keys=NG_FORECAST_DAILY.keys)
        if since is not None:
            df = df[df["gas_day"] >= pd.Timestamp(since)]
        issues = df[df["item"] == "demand_forecast"].groupby(["gas_day", "ldz"]).size()
        logger.info(f"Parsed {len(pulls)} archived pull(s) -> {len(df)} rows; "
                    f"{issues.median():.0f} demand issues per gas day and LDZ (median)")
        return self.store.write(NG_FORECAST_DAILY, df.drop(columns="_pulled"), on_conflict="replace")


def parse(content: bytes) -> pd.DataFrame:
    """Portal forecast CSV -> NG_FORECAST_DAILY rows. Unrecognised data items raise."""
    raw = read_portal_csv(content)
    lookup = {name: identify_forecast(name) for name in raw["Data Item"].unique()}
    unknown = [name for name, hit in lookup.items() if hit is None]
    if unknown:
        raise NationalGasError(f"Unrecognised forecast items: {unknown}")

    hits = [lookup[name] for name in raw["Data Item"]]
    cols = common_columns(raw)
    out = pd.DataFrame({
        **cols,
        "ldz": [ldz for _, ldz in hits],
        "item": [item.name for item, _ in hits],
        "data_item_id": [item.ids[ldz] for item, ldz in hits],
        "unit": [item.unit for item, _ in hits],
    }).rename(columns={"applicable_at": "issued_at"})
    out["issue_day"] = (out["issued_at"].dt.normalize() - out["gas_day"]).dt.days
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.build.ng_forecast_daily")
    parser.add_argument("--since", type=date.fromisoformat, help="only rebuild from this gas day")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = create_config()
    builder = NGForecastDailyBuilder(get_store(config), resolve_path(config, "storage", "raw_dir"))
    logger.info(f"Done: {builder.build(args.since)} rows written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
