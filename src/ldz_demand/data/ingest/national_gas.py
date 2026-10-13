"""
National Gas Transmission data portal ingestor — download and archive only.

Public CSV API, no auth. Three series, each archived untouched (the portal keeps a rolling ~5 years):

- "ldz": per-LDZ daily demand (total, DM, NDM, UIG), calorific value and actual CWV (ITEMS)
  -> raw_dir/national_gas/<year>/ng_ldz_<start>_<end>_pulled_<UTC time>.csv
- "offtakes": energy offtaken from the NTS at each LDZ offtake point (OFFTAKES), used to check
  the published LDZ totals
  -> raw_dir/national_gas/offtakes/<year>/ng_offtakes_<start>_<end>_pulled_<UTC time>.csv
- "forecasts": National Gas's own forecasts per LDZ — total demand and the CWV — with EVERY issue
  kept (latestFlag=N: ~8 demand issues per gas day, from D-1 afternoon to the end of D), the
  benchmark our forecasts are compared with (FORECAST_ITEMS)
  -> raw_dir/national_gas/forecasts/<year>/ng_forecasts_<start>_<end>_pulled_<UTC time>.csv

The archive is the source of truth: tables are built from it by ldz_demand.data.build.

Units differ by item — total demand is in mcm, DM/NDM/UIG in kWh — see ITEMS.

Run as a script:
    python -m ldz_demand.data.ingest.national_gas refresh                    # both series
    python -m ldz_demand.data.ingest.national_gas refresh --series offtakes
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
SERIES = ("ldz", "offtakes", "forecasts")
ARCHIVE = {  # series -> (sub-folder of raw_dir/national_gas, filename prefix)
    "ldz": ("", "ng_ldz"),
    "offtakes": ("offtakes", "ng_offtakes"),
    "forecasts": ("forecasts", "ng_forecasts"),
}
LATEST_ONLY = {"ldz": True, "offtakes": True, "forecasts": False}  # forecasts: keep every issue

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


# National Gas forecasts, from the portal catalogue, checked 2026-10-13. "Demand Forecast, LDZ" is total LDZ
# demand (mcm), re-issued after each UNC forecast run; the CWV forecasts are issued on the gas day (D) and
# the day before (D-1).
FORECAST_ITEMS: dict[str, Item] = {i.name: i for i in (
    _item("demand_forecast", "mcm", r"Demand Forecast, LDZ \((\w\w)\)", {
        "EA": "PUBOB609", "EM": "PUBOB610", "NE": "PUBOB611", "NO": "PUBOB612", "NT": "PUBOB613",
        "NW": "PUBOB614", "SC": "PUBOB615", "SE": "PUBOB616", "SO": "PUBOB617", "SW": "PUBOB618",
        "WM": "PUBOB619", "WN": "PUBOB620", "WS": "PUBOB621"}),
    _item("cwv_forecast_d", "degC", r"Composite Weather Variable, Forecast, LDZ\((\w\w)\), D", {
        "EA": "PUBOB3713", "EM": "PUBOB3714", "NE": "PUBOB3715", "NO": "PUBOB3716", "NT": "PUBOB3717",
        "NW": "PUBOB3718", "SC": "PUBOB3721", "SE": "PUBOB3719", "SO": "PUBOB3720", "SW": "PUBOB3722",
        "WM": "PUBOB3723", "WN": "PUBOB3724", "WS": "PUBOB3725"}),
    _item("cwv_forecast_d_minus_1", "degC", r"Composite Weather Variable, Forecast, LDZ\((\w\w)\), D-1", {
        "EA": "PUBOB3726", "EM": "PUBOB3727", "NE": "PUBOB3728", "NO": "PUBOB3729", "NT": "PUBOB3730",
        "NW": "PUBOB3731", "SC": "PUBOB3734", "SE": "PUBOB3732", "SO": "PUBOB3733", "SW": "PUBOB3735",
        "WM": "PUBOB3736", "WN": "PUBOB3737", "WS": "PUBOB3738"}),
)}


# Energy offtaken (kWh) at each NTS -> LDZ offtake point, from the portal catalogue, checked 2026-10-11.
# LDZ -> {site: id}. Peters Green has two items: one published under NT, and one under "SM" whose
# physical-flow item is labelled "SM, NT" — it also feeds North Thames, so it sits in NT as PetersGrnSM.
OFFTAKES: dict[str, dict[str, str]] = {
    "EA": {"Bacton": "PUBOBJ858", "Brisley": "PUBOBJ867", "GtWilbraham": "PUBOBJ893", "MatchngGreen": "PUBOBJ918", "PeterborEye": "PUBOBJ927", "RoudhamHeath": "PUBOBJ936", "Royston": "PUBOBJ937", "WestWinch": "PUBOBJ958", "Whitwell": "PUBOBJ961", "Yelverton": "PUBOBJ965"},
    "EM": {"Alrewas": "PUBOBJ847", "Blaby": "PUBOBJ862", "Blyborough": "PUBOBJ864", "Caldecott": "PUBOBJ870", "Drointon": "PUBOBJ880", "Gosberton": "PUBOBJ892", "Kirkstead": "PUBOBJ906", "MktHarborogh": "PUBOBJ922", "SilkWillough": "PUBOBJ945", "SuttonBridge": "PUBOBJ949", "ThorntonCurt": "PUBOBJ951", "TurLangton": "PUBOBJ955", "Walesby": "PUBOBJ956"},
    "NE": {"Asselby": "PUBOBJ851", "Baldersby": "PUBOBJ859", "BurleyBank": "PUBOBJ869", "Ganstead": "PUBOBJ889", "LtBurdon": "PUBOBJ912", "Pannal": "PUBOBJ924", "Paull": "PUBOBJ926", "Pickering": "PUBOBJ930", "Rawcliffe": "PUBOBJ933", "Towton": "PUBOBJ954"},
    "NO": {"Auckland": "PUBOBJ852", "AucklandTF": "PUBOBJ853", "Coldstream": "PUBOBJ876", "Corbridge": "PUBOBJ877", "CowpenBewley": "PUBOBJ878", "Elton": "PUBOBJ885", "Guyzance": "PUBOBJ894", "Humbleton": "PUBOBJ898", "Keld": "PUBOBJ903", "Melkinthorpe": "PUBOBJ919", "Saltwick": "PUBOBJ939", "SaltwickH": "PUBOBJ940", "Thrintoft": "PUBOBJ952", "TowLaw": "PUBOBJ953", "Wetheral": "PUBOBJ960"},
    "NT": {"PetersGrnSM": "PUBOBJ929", "Horndon": "PUBOBJ897", "LuxboroughLn": "PUBOBJ914", "PetersGrn": "PUBOBJ928", "Winkfield": "PUBOBJ962"},
    "NW": {"Audley": "PUBOBJ854", "Blackrod": "PUBOBJ863", "Eccleston": "PUBOBJ884", "HolmesChapel": "PUBOBJ896", "Lupton": "PUBOBJ913", "Malpas": "PUBOBJ916", "MickleTrafd": "PUBOBJ920", "Partington": "PUBOBJ925", "Samlesbury": "PUBOBJ941", "Warburton": "PUBOBJ957", "WestonPoint": "PUBOBJ959"},
    "SC": {"Aberdeen": "PUBOBJ846", "Armadale": "PUBOBJ849", "Balgray": "PUBOBJ860", "Bathgate": "PUBOBJ861", "Broxburn": "PUBOBJ868", "Burnhervie": "PUBOBJ2031", "Careston": "PUBOBJ871", "Drum": "PUBOBJ881", "Glenmavis": "PUBOBJ891", "Hume": "PUBOBJ899", "Kinknockie": "PUBOBJ905", "Langholm": "PUBOBJ907", "Lockerbie": "PUBOBJ910", "NetherHwclgh": "PUBOBJ923", "Pitcairn": "PUBOBJ931", "Soutra": "PUBOBJ946", "StFergus": "PUBOBJ947"},
    "SE": {"Farningham": "PUBOBJ887", "FarninghamB": "PUBOBJ2028", "Shorne": "PUBOBJ943", "Tatsfield": "PUBOBJ950", "Winkfield": "PUBOBJ963"},
    "SO": {"BraishfieldA": "PUBOBJ865", "BraishfieldB": "PUBOBJ866", "Hardwick": "PUBOBJ895", "Ipsden1": "PUBOBJ901", "Ipsden2": "PUBOBJ902", "Mappowder": "PUBOBJ917", "Winkfield": "PUBOBJ964"},
    "SW": {"Aylesbeare": "PUBOBJ857", "Choakford": "PUBOBJ872", "Cirencester": "PUBOBJ874", "Coffinswell": "PUBOBJ875", "EastonGrey": "PUBOBJ883", "Evesham": "PUBOBJ886", "Fiddington": "PUBOBJ888", "Ilchester": "PUBOBJ900", "Kenn": "PUBOBJ904", "LittletnDrew": "PUBOBJ909", "Pucklechurch": "PUBOBJ932", "Ross": "PUBOBJ934", "Seabank": "PUBOBJ942"},
    "WM": {"Alrewas": "PUBOBJ848", "Aspley": "PUBOBJ850", "Audley": "PUBOBJ855", "Austrey": "PUBOBJ856", "Churchovr": "PUBOBJ873", "Leamington": "PUBOBJ908", "LowerQuinton": "PUBOBJ911", "Milwich": "PUBOBJ921", "Ross": "PUBOBJ935", "Rugby": "PUBOBJ938", "Shustoke": "PUBOBJ944", "StratfrdAvon": "PUBOBJ948"},
    "WN": {"Maelor": "PUBOBJ915"},
    "WS": {"Dowlais": "PUBOBJ879", "DyffrynClyd": "PUBOBJ882", "Gilwern": "PUBOBJ890"},
}
OFFTAKE_UNIT = "kWh"
OFFTAKE_PATTERN = re.compile(r"NTS Energy Offtaken, (\w+), (\w\w), LDZ Offtake")
PUBLISHED_ALIASES = {("PetersGrn", "SM"): ("NT", "PetersGrnSM")}  # (site, code) -> (LDZ, site)


class NationalGasError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArchivedPull:
    path: Path
    start: date
    end: date
    pulled: str  # UTC timestamp from the filename; sorts chronologically


def archived_pulls(raw_dir: Path, series: str = "ldz") -> list[ArchivedPull]:
    """Archived responses for a series, oldest pull first."""
    folder, prefix = ARCHIVE[series]
    name = re.compile(rf"{prefix}_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}}-\d{{2}}-\d{{2}})_pulled_(\w+)\.csv")
    pulls = []
    for path in (Path(raw_dir) / "national_gas" / folder).rglob("*.csv"):
        if m := name.fullmatch(path.name):
            pulls.append(ArchivedPull(path, date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2)), m.group(3)))
    return sorted(pulls, key=lambda p: p.pulled)


class NationalGasIngestor:
    """
    Downloads one National Gas series and archives the raw responses.

    Parameters
    ----------
    raw_dir : Path
        Raw archive root; responses go under raw_dir/national_gas/ (see ARCHIVE).
    series : str
        "ldz" (ITEMS per LDZ), "offtakes" (OFFTAKES) or "forecasts" (FORECAST_ITEMS, every issue).
    items, ldzs : sequence of str, optional
        Subset to pull. items applies to "ldz" only. Defaults to everything.
    session : requests.Session, optional
        Injectable for testing.
    """

    def __init__(self, raw_dir: Path, series: str = "ldz", items=None, ldzs=None, session=None) -> None:
        if series not in SERIES:
            raise ValueError(f"series must be one of {SERIES}, got '{series}'")
        self.raw_dir = Path(raw_dir)
        self.series = series
        self.items = [ITEMS[name] for name in (items or ITEMS)]
        self.ldzs = list(ldzs or LDZS)
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    @property
    def ids(self) -> list[str]:
        if self.series == "offtakes":
            return [i for ldz in self.ldzs for i in OFFTAKES[ldz].values()]
        if self.series == "forecasts":
            return [item.ids[ldz] for item in FORECAST_ITEMS.values() for ldz in self.ldzs]
        return [item.ids[ldz] for item in self.items for ldz in self.ldzs]

    def pull(self, start: date, end: date) -> list[Path]:
        """Download [start, end] in calendar-year chunks. Returns the archived files."""
        return [self.archive(self.fetch(s, e), s, e) for s, e in _year_chunks(start, end)]

    def refresh(self, today: date | None = None) -> list[Path]:
        """Download from the last archived gas day (minus a lookback) to yesterday; full history if none."""
        today = today or date.today()
        pulls = archived_pulls(self.raw_dir, self.series)
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
            "latestFlag": "Y" if LATEST_ONLY[self.series] else "N",
            "ids": ",".join(self.ids),
            "type": "CSV",
        }
        logger.info(f"Fetching {len(self.ids)} {self.series} series for {start}..{end}")
        response = self.session.get(BASE_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        if not response.content.lstrip(b"\xef\xbb\xbf").startswith(b"Applicable At"):
            raise NationalGasError(f"Unexpected response for {start}..{end}: {response.content[:200]!r}")
        return response.content

    def archive(self, content: bytes, start: date, end: date) -> Path:
        """Write the raw response to a new file; never overwrites."""
        pulled = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        folder, prefix = ARCHIVE[self.series]
        path = self.raw_dir / "national_gas" / folder / str(start.year) / f"{prefix}_{start}_{end}_pulled_{pulled}.csv"
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


def identify_forecast(data_item: str) -> tuple[Item, str] | None:
    """Portal forecast "Data Item" text -> (Item, LDZ), or None if it isn't one of FORECAST_ITEMS."""
    for item in FORECAST_ITEMS.values():
        match = item.pattern.fullmatch(data_item)
        if match and match.group(1) in item.ids:
            return item, match.group(1)
    return None


def identify_offtake(data_item: str) -> tuple[str, str, str] | None:
    """Portal offtake "Data Item" text -> (LDZ, site, id), or None if it isn't one of OFFTAKES."""
    match = OFFTAKE_PATTERN.fullmatch(data_item)
    if not match:
        return None
    ldz, site = PUBLISHED_ALIASES.get((match.group(1), match.group(2)), (match.group(2), match.group(1)))
    data_id = OFFTAKES.get(ldz, {}).get(site)
    return (ldz, site, data_id) if data_id else None


def _year_chunks(start: date, end: date):
    current = start
    while current <= end:
        chunk_end = min(date(current.year, 12, 31), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.data.ingest.national_gas")
    sub = parser.add_subparsers(dest="command", required=True)
    refresh_parser = sub.add_parser("refresh", help="download from the last archived day (full history if none)")
    pull_parser = sub.add_parser("pull", help="download an explicit gas-day range")
    pull_parser.add_argument("start", type=date.fromisoformat)
    pull_parser.add_argument("end", type=date.fromisoformat)
    for p in (refresh_parser, pull_parser):
        p.add_argument("--series", choices=[*SERIES, "all"], default="all")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = create_config()
    raw_dir = resolve_path(config, "storage", "raw_dir")
    for series in (SERIES if args.series == "all" else [args.series]):
        ingestor = NationalGasIngestor(raw_dir, series=series)
        files = ingestor.refresh() if args.command == "refresh" else ingestor.pull(args.start, args.end)
        logger.info(f"{series}: {len(files)} file(s) archived")
    logger.info("Build the tables with: python -m ldz_demand.data.build.ng_ldz_daily, "
                "ng_offtake_daily and ng_forecast_daily")
    return 0


if __name__ == "__main__":
    sys.exit(main())
