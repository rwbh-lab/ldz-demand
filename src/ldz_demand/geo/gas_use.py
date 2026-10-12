"""
Annual gas use by local authority (DESNZ subnational gas consumption statistics).

Annual, weather-corrected official statistics (Open Government Licence v3.0) — used as a map of
*where* gas is used (weights, and a check of LDZ membership), not to test the daily weather
response. The latest year is shipped as a small derived CSV; building it needs openpyxl (geo extra).
"""

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent / "data" / "desnz_la_gas.csv"
SOURCE_URL = ("https://assets.publishing.service.gov.uk/media/69f9bf208f3213f7384ecae6/"
              "Subnational_gas_consumption_statistics_2005-2024.xlsx")
RAW_NAME = "Subnational_gas_consumption_statistics_2005-2024.xlsx"
YEAR = "2024"
ATTRIBUTION = "Source: DESNZ subnational gas consumption statistics (2024), Open Government Licence v3.0."
COLUMNS = {
    "Code": "lad24cd",
    "Local authority": "la_name",
    "Number of meters (thousands): Domestic": "meters_domestic_k",
    "Number of meters (thousands): All meters": "meters_all_k",
    "Total consumption (GWh): Domestic": "gwh_domestic",
    "Total consumption (GWh): All meters": "gwh_all",
}


def fetch(raw_dir: Path, session: requests.Session | None = None) -> Path:
    path = Path(raw_dir) / "reference" / "desnz" / RAW_NAME
    if path.exists():
        return path
    session = session or requests.Session()
    response = session.get(SOURCE_URL, timeout=300)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    logger.info(f"Fetched DESNZ gas consumption -> {path}")
    return path


def build(raw_dir: Path, out: Path = DATA_FILE) -> Path:
    raw = pd.read_excel(Path(raw_dir) / "reference" / "desnz" / RAW_NAME, sheet_name=YEAR, header=5)
    raw.columns = [" ".join(str(c).split()) for c in raw.columns]
    rows = raw[raw["Local authority"].notna() & ~raw["Local authority"].isin(["All local authorities", "Unallocated"])]
    df = rows[list(COLUMNS)].rename(columns=COLUMNS)
    num = [c for c in df.columns if c not in ("lad24cd", "la_name")]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce").round(3)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        f.write(f"# {ATTRIBUTION} Year {YEAR}; weather-corrected.\n")
        df.to_csv(f, index=False)
    logger.info(f"Wrote {len(df)} local authorities -> {out}")
    return out


@lru_cache(maxsize=1)
def load() -> pd.DataFrame:
    return pd.read_csv(DATA_FILE, comment="#", dtype={"lad24cd": str})
