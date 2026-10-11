"""
Builds ng_offtake_daily from the archived National Gas offtake responses.

Energy offtaken from the NTS at each LDZ offtake point (kWh/day). Summed per LDZ it is an independent
meter of gas entering the LDZ from the NTS, used to check the published LDZ totals — e.g. SE's total
normally includes a steady non-NTS input that went missing from the published total in 2022-24.
Same rules as ng_ldz_daily: newest pull with a value wins; rows written with replace.

Run as a script:
    python -m ldz_demand.data.build.ng_offtake_daily [--since 2026-09-01]
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from ldz_demand.config import create_config, resolve_path
from ldz_demand.data.build.ng_ldz_daily import common_columns, latest_values, log_coverage, read_portal_csv
from ldz_demand.data.datasets import NG_OFFTAKE_DAILY
from ldz_demand.data.ingest.national_gas import OFFTAKE_UNIT, NationalGasError, archived_pulls, identify_offtake
from ldz_demand.data.store import Store, get_store

logger = logging.getLogger(__name__)


class NGOfftakeDailyBuilder:
    """
    Parameters
    ----------
    store : Store
        Destination for NG_OFFTAKE_DAILY.
    raw_dir : Path
        Raw archive root (offtake files are under raw_dir/national_gas/offtakes).
    """

    def __init__(self, store: Store, raw_dir: Path) -> None:
        self.store = store
        self.raw_dir = Path(raw_dir)

    def build(self, since: date | None = None) -> int:
        pulls = [p for p in archived_pulls(self.raw_dir, "offtakes") if since is None or p.end >= since]
        if not pulls:
            logger.warning(f"No archived offtake pulls under {self.raw_dir / 'national_gas' / 'offtakes'}")
            return 0

        frames = [parse(p.path.read_bytes()).assign(_pulled=p.pulled) for p in pulls]
        df = latest_values(pd.concat(frames, ignore_index=True), keys=NG_OFFTAKE_DAILY.keys)
        if since is not None:
            df = df[df["gas_day"] >= pd.Timestamp(since)]
        logger.info(f"Parsed {len(pulls)} archived pull(s) -> {len(df)} rows")
        log_coverage(df, series=("site", "ldz"))
        return self.store.write(NG_OFFTAKE_DAILY, df.drop(columns="_pulled"), on_conflict="replace")


def parse(content: bytes) -> pd.DataFrame:
    """Portal offtake CSV -> NG_OFFTAKE_DAILY rows. Unrecognised data items raise."""
    raw = read_portal_csv(content)
    lookup = {name: identify_offtake(name) for name in raw["Data Item"].unique()}
    unknown = [name for name, hit in lookup.items() if hit is None]
    if unknown:
        raise NationalGasError(f"Unrecognised offtake items: {unknown}")

    hits = [lookup[name] for name in raw["Data Item"]]
    return pd.DataFrame({
        **common_columns(raw),
        "ldz": [ldz for ldz, _, _ in hits],
        "site": [site for _, site, _ in hits],
        "data_item_id": [data_id for _, _, data_id in hits],
        "unit": OFFTAKE_UNIT,
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.build.ng_offtake_daily")
    parser.add_argument("--since", type=date.fromisoformat, help="only rebuild from this gas day")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = create_config()
    builder = NGOfftakeDailyBuilder(get_store(config), resolve_path(config, "storage", "raw_dir"))
    logger.info(f"Done: {builder.build(args.since)} rows written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
