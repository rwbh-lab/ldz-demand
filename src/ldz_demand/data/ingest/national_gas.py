"""
National Gas Transmission data portal ingestor — download and archive only.

Public CSV API, no auth: per-LDZ daily demand (total, DM, NDM, UIG), calorific value and actual CWV.
History is a rolling ~5 years, so every response is archived untouched under
raw_dir/national_gas/<year>/ng_ldz_<start>_<end>_pulled_<UTC time>.csv. The archive is the source
of truth: the ng_ldz_daily table is built from it by ldz_demand.data.build.ng_ldz_daily.

Units differ by item — total demand is in mcm, DM/NDM/UIG in kWh — see ITEMS.

Run as a script:
    python -m ldz_demand.data.ingest.national_gas refresh
    python -m ldz_demand.data.ingest.national_gas pull 2021-10-01 2026-10-10
"""

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from ldz_demand.config import create_config, resolve_path

logger = logging.getLogger(__name__)

BASE_URL = "https://data.nationalgas.com/api/find-gas-data-download"
USER_AGENT = "ldz-demand/0.1"  # the portal rejects Python's default urllib user agent
TIMEOUT = 300  # seconds; a full year of all items is ~4 MB and takes ~15 s
HISTORY_DAYS = 5 * 365  # the portal keeps a rolling ~5 years
REFRESH_LOOKBACK_DAYS = 10  # re-pull recent days so D+6 closed-out values replace provisional gaps
ARCHIVE_NAME = re.compile(r"ng_ldz_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_pulled_(\w+)\.csv")

LDZS = ("EA", "EM", "NE", "NO", "NT", "NW", "SC", "SE", "SO", "SW", "WM", "WN", "WS")


@dataclass(frozen=True)
class Item:
    name: str
    unit: str
    pattern: re.Pattern  # matches the portal's "Data Item" text; group 1 is the LDZ
    ids: dict[str, str]  # LDZ -> PUBOB id. Not in LDZ order — always look up, never compute.


def _item(name: str, unit: str, pattern: str, ids: dict[str, str]) -> Item:
    return Item(name, unit, re.compile(pattern), ids)


# IDs from the portal catalogue (find-gas-data-folders), checked 2026-10-11.
ITEMS: dict[str, Item] = {i.name: i for i in (
    _item("demand_total_d1", "mcm", r"Demand Actual, LDZ \((\w\w)\), D\+1", {
        "EA": "PUBOB624", "EM": "PUBOB625", "NE": "PUBOB626", "NO": "PUBOB627", "NT": "PUBOB628",
        "NW": "PUBOB629", "SC": "PUBOB630", "SE": "PUBOB631", "SO": "PUBOB632", "SW": "PUBOB633",
        "WM": "PUBOB634", "WN": "PUBOB635", "WS": "PUBOB636"}),
    _item("demand_total_d6", "mcm", r"Demand Actual, LDZ \((\w\w)\), D\+6", {
        "EA": "PUBOB639", "EM": "PUBOB640", "NE": "PUBOB641", "NO": "PUBOB642", "NT": "PUBOB643",
        "NW": "PUBOB644", "SC": "PUBOB645", "SE": "PUBOB646", "SO": "PUBOB647", "SW": "PUBOB648",
        "WM": "PUBOB649", "WN": "PUBOB650", "WS": "PUBOB651"}),
    _item("demand_dm_d1", "kWh", r"Demand, Actual DM, LDZ\((\w\w)\), D\+1", {
        "EA": "PUBOB3742", "EM": "PUBOB3743", "NE": "PUBOB3744", "NO": "PUBOB3745", "NT": "PUBOB3746",
        "NW": "PUBOB3747", "SC": "PUBOB3748", "SE": "PUBOB3749", "SO": "PUBOB3750", "SW": "PUBOB3751",
        "WM": "PUBOB3754", "WN": "PUBOB3752", "WS": "PUBOB3753"}),
    _item("demand_dm_d6", "kWh", r"Demand, Actual DM, LDZ\((\w\w)\), D\+6", {
        "EA": "PUBOB3768", "EM": "PUBOB3769", "NE": "PUBOB3770", "NO": "PUBOB3771", "NT": "PUBOB3772",
        "NW": "PUBOB3773", "SC": "PUBOB3774", "SE": "PUBOB3775", "SO": "PUBOB3776", "SW": "PUBOB3777",
        "WM": "PUBOB3780", "WN": "PUBOB3778", "WS": "PUBOB3779"}),
    _item("demand_ndm_d1", "kWh", r"Demand, Actual NDM, LDZ\((\w\w)\), D\+1", {
        "EA": "PUBOB3755", "EM": "PUBOB3756", "NE": "PUBOB3757", "NO": "PUBOB3758", "NT": "PUBOB3759",
        "NW": "PUBOB3760", "SC": "PUBOB3761", "SE": "PUBOB3762", "SO": "PUBOB3763", "SW": "PUBOB3764",
        "WM": "PUBOB3767", "WN": "PUBOB3765", "WS": "PUBOB3766"}),
    _item("demand_ndm_d6", "kWh", r"Demand, Actual NDM, LDZ\((\w\w)\), D\+6", {
        "EA": "PUBOB3781", "EM": "PUBOB3782", "NE": "PUBOB3783", "NO": "PUBOB3784", "NT": "PUBOB3785",
        "NW": "PUBOB3786", "SC": "PUBOB3787", "SE": "PUBOB3788", "SO": "PUBOB3789", "SW": "PUBOB3790",
        "WM": "PUBOB3793", "WN": "PUBOB3791", "WS": "PUBOB3792"}),
    _item("demand_uig_d1", "kWh", r"Demand, Actual UIG, LDZ\((\w\w)\), D\+1", {
        "EA": "PUBOBJ2471", "EM": "PUBOBJ2472", "NE": "PUBOBJ2473", "NO": "PUBOBJ2474", "NT": "PUBOBJ2475",
        "NW": "PUBOBJ2476", "SC": "PUBOBJ2477", "SE": "PUBOBJ2478", "SO": "PUBOBJ2479", "SW": "PUBOBJ2480",
        "WM": "PUBOBJ2483", "WN": "PUBOBJ2481", "WS": "PUBOBJ2482"}),
    _item("demand_uig_d6", "kWh", r"Demand, Actual UIG, LDZ\((\w\w)\), D\+6", {
        "EA": "PUBOBJ2484", "EM": "PUBOBJ2485", "NE": "PUBOBJ2486", "NO": "PUBOBJ2487", "NT": "PUBOBJ2488",
        "NW": "PUBOBJ2489", "SC": "PUBOBJ2490", "SE": "PUBOBJ2491", "SO": "PUBOBJ2492", "SW": "PUBOBJ2493",
        "WM": "PUBOBJ2496", "WN": "PUBOBJ2494", "WS": "PUBOBJ2495"}),
    _item("cv", "MJ/m3", r"Calorific Value, LDZ\((\w\w)\)", {
        "EA": "PUBOB4507", "EM": "PUBOB4508", "NE": "PUBOB4510", "NO": "PUBOB4509", "NT": "PUBOB4511",
        "NW": "PUBOB4512", "SC": "PUBOB4513", "SE": "PUBOB4514", "SO": "PUBOB4515", "SW": "PUBOB4516",
        "WM": "PUBOB4517", "WN": "PUBOB4518", "WS": "PUBOB4519"}),
    _item("cwv_actual", "degC", r"Composite Weather Variable, Actual, LDZ\((\w\w)\), D\+1", {
        "EA": "PUBOB3700", "EM": "PUBOB3701", "NE": "PUBOB3702", "NO": "PUBOB3703", "NT": "PUBOB3704",
        "NW": "PUBOB3705", "SC": "PUBOB3708", "SE": "PUBOB3706", "SO": "PUBOB3707", "SW": "PUBOB3709",
        "WM": "PUBOB3710", "WN": "PUBOB3711", "WS": "PUBOB3712"}),
)}


class NationalGasError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArchivedPull:
    path: Path
    start: date
    end: date
    pulled: str  # UTC timestamp from the filename; sorts chronologically


def archived_pulls(raw_dir: Path) -> list[ArchivedPull]:
    """Archived responses under raw_dir/national_gas, oldest pull first."""
    pulls = []
    for path in (Path(raw_dir) / "national_gas").rglob("*.csv"):
        if m := ARCHIVE_NAME.fullmatch(path.name):
            pulls.append(ArchivedPull(path, date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2)), m.group(3)))
    return sorted(pulls, key=lambda p: p.pulled)


class NationalGasIngestor:
    """
    Downloads National Gas LDZ data items and archives the raw responses.

    Parameters
    ----------
    raw_dir : Path
        Raw archive root; responses go to raw_dir/national_gas/<year>/.
    items, ldzs : sequence of str, optional
        Subset to pull. Defaults to all ITEMS and all LDZS.
    session : requests.Session, optional
        Injectable for testing.
    """

    def __init__(self, raw_dir: Path, items=None, ldzs=None, session=None) -> None:
        self.raw_dir = Path(raw_dir)
        self.items = [ITEMS[name] for name in (items or ITEMS)]
        self.ldzs = list(ldzs or LDZS)
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    @property
    def ids(self) -> list[str]:
        return [item.ids[ldz] for item in self.items for ldz in self.ldzs]

    def pull(self, start: date, end: date) -> list[Path]:
        """Download [start, end] in calendar-year chunks. Returns the archived files."""
        return [self.archive(self.fetch(s, e), s, e) for s, e in _year_chunks(start, end)]

    def refresh(self, today: date | None = None) -> list[Path]:
        """Download from the last archived gas day (minus a lookback) to yesterday; full history if none."""
        today = today or date.today()
        pulls = archived_pulls(self.raw_dir)
        if pulls:
            start = max(p.end for p in pulls) - timedelta(days=REFRESH_LOOKBACK_DAYS)
        else:
            start = today - timedelta(days=HISTORY_DAYS)
        return self.pull(start, today - timedelta(days=1))

    def fetch(self, start: date, end: date) -> bytes:
        params = {
            "applicableFor": "Y",
            "dateFrom": start.isoformat(),
            "dateTo": end.isoformat(),
            "dateType": "GASDAY",
            "latestFlag": "Y",
            "ids": ",".join(self.ids),
            "type": "CSV",
        }
        logger.info(f"Fetching {len(self.ids)} series for {start}..{end}")
        response = self.session.get(BASE_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        if not response.content.lstrip(b"\xef\xbb\xbf").startswith(b"Applicable At"):
            raise NationalGasError(f"Unexpected response for {start}..{end}: {response.content[:200]!r}")
        return response.content

    def archive(self, content: bytes, start: date, end: date) -> Path:
        """Write the raw response to a new file; never overwrites."""
        pulled = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.raw_dir / "national_gas" / str(start.year) / f"ng_ldz_{start}_{end}_pulled_{pulled}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as f:
            f.write(content)
        logger.info(f"Archived raw response to {path}")
        return path


def identify(data_item: str) -> tuple[Item, str] | None:
    """Portal "Data Item" text -> (Item, LDZ), or None if it isn't one of ITEMS."""
    for item in ITEMS.values():
        match = item.pattern.fullmatch(data_item)
        if match and match.group(1) in item.ids:
            return item, match.group(1)
    return None


def _year_chunks(start: date, end: date):
    current = start
    while current <= end:
        chunk_end = min(date(current.year, 12, 31), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.ingest.national_gas")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("refresh", help="download from the last archived day (full history if none)")
    pull_parser = sub.add_parser("pull", help="download an explicit gas-day range")
    pull_parser.add_argument("start", type=date.fromisoformat)
    pull_parser.add_argument("end", type=date.fromisoformat)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = create_config()
    ingestor = NationalGasIngestor(resolve_path(config, "storage", "raw_dir"))
    files = ingestor.refresh() if args.command == "refresh" else ingestor.pull(args.start, args.end)
    logger.info(f"Done: {len(files)} file(s) archived. Build the table with: python -m ldz_demand.data.build.ng_ldz_daily")
    return 0


if __name__ == "__main__":
    sys.exit(main())
