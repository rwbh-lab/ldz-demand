"""
Builds ng_ldz_daily from the archived National Gas responses.

Every archived pull is parsed; where pulls overlap, the most recent pull with a value wins (an older
value is kept over a newer blank, e.g. a D+6 figure not yet closed out). Rows are written with
replace, so rebuilding is safe and idempotent.

Run as a script:
    python -m ldz_demand.data.build.ng_ldz_daily                     # full rebuild from the archive
    python -m ldz_demand.data.build.ng_ldz_daily --since 2026-09-01  # only pulls/rows from that day
"""

import argparse
import io
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from ldz_demand.config import create_config, resolve_path
from ldz_demand.data.datasets import NG_LDZ_DAILY
from ldz_demand.data.ingest.national_gas import NationalGasError, archived_pulls, identify
from ldz_demand.data.store import Store, get_store

logger = logging.getLogger(__name__)

COLUMNS = ["Applicable At", "Applicable For", "Data Item", "Value", "Generated Time", "Quality Indicator"]


class NGLdzDailyBuilder:
    """
    Parameters
    ----------
    store : Store
        Destination for NG_LDZ_DAILY.
    raw_dir : Path
        Raw archive root (the National Gas files are under raw_dir/national_gas).
    """

    def __init__(self, store: Store, raw_dir: Path) -> None:
        self.store = store
        self.raw_dir = Path(raw_dir)

    def build(self, since: date | None = None) -> int:
        """Parse archived pulls (those reaching `since`, if given) and write the table. Returns rows written."""
        pulls = [p for p in archived_pulls(self.raw_dir) if since is None or p.end >= since]
        if not pulls:
            logger.warning(f"No archived National Gas pulls under {self.raw_dir / 'national_gas'}")
            return 0

        frames = [parse(p.path.read_bytes()).assign(_pulled=p.pulled) for p in pulls]
        df = latest_values(pd.concat(frames, ignore_index=True))
        if since is not None:
            df = df[df["gas_day"] >= pd.Timestamp(since)]
        logger.info(f"Parsed {len(pulls)} archived pull(s) -> {len(df)} rows")
        log_coverage(df)
        return self.store.write(NG_LDZ_DAILY, df.drop(columns="_pulled"), on_conflict="replace")


def parse(content: bytes) -> pd.DataFrame:
    """Portal CSV -> NG_LDZ_DAILY rows. Unrecognised data items raise rather than being dropped."""
    raw = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if list(raw.columns) != COLUMNS:
        raise NationalGasError(f"Unexpected columns {list(raw.columns)}")

    lookup = {name: identify(name) for name in raw["Data Item"].unique()}
    unknown = [name for name, hit in lookup.items() if hit is None]
    if unknown:
        raise NationalGasError(f"Unrecognised data items: {unknown}")

    hits = [lookup[name] for name in raw["Data Item"]]
    return pd.DataFrame({
        "gas_day": pd.to_datetime(raw["Applicable For"], format="%d/%m/%Y"),
        "ldz": [ldz for _, ldz in hits],
        "item": [item.name for item, _ in hits],
        "data_item_id": [item.ids[ldz] for item, ldz in hits],
        "value": pd.to_numeric(raw["Value"].replace("", None)),
        "unit": [item.unit for item, _ in hits],
        "quality": raw["Quality Indicator"].replace("", None),
        "applicable_at": pd.to_datetime(raw["Applicable At"].replace("", None), format="%d/%m/%Y %H:%M:%S"),
        "generated_time": pd.to_datetime(raw["Generated Time"].replace("", None), format="%d/%m/%Y %H:%M:%S"),
    })


def latest_values(df: pd.DataFrame) -> pd.DataFrame:
    """One row per key: the most recent pull that has a value, else the most recent pull."""
    keys = list(NG_LDZ_DAILY.keys)
    ranked = df.assign(_has_value=df["value"].notna()).sort_values([*keys, "_has_value", "_pulled"])
    return ranked.drop_duplicates(keys, keep="last").drop(columns="_has_value").reset_index(drop=True)


def log_coverage(df: pd.DataFrame) -> None:
    """Warn about gaps inside each series' own date range (so late-starting series, e.g. UIG, aren't flagged)."""
    present = df[df["value"].notna()]
    gaps = []
    for (item, ldz), days in present.groupby(["item", "ldz"])["gas_day"]:
        span = (days.max() - days.min()).days + 1
        if (missing := span - days.nunique()) > 0:
            gaps.append(f"{item}/{ldz}={missing}d")
    if gaps:
        logger.warning(f"Gaps within series ranges: {', '.join(gaps[:10])}{' ...' if len(gaps) > 10 else ''}")
    else:
        logger.info(f"No gaps within series ranges ({present.groupby(['item', 'ldz']).ngroups} series)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.build.ng_ldz_daily")
    parser.add_argument("--since", type=date.fromisoformat, help="only rebuild from this gas day")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = create_config()
    builder = NGLdzDailyBuilder(get_store(config), resolve_path(config, "storage", "raw_dir"))
    written = builder.build(args.since)
    logger.info(f"Done: {written} rows written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
