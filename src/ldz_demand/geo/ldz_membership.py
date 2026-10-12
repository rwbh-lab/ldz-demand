"""
LDZ membership: which local authority (and, inside split authorities, which town) is in which LDZ.

There is no public official LDZ boundary file, so membership is derived:

1. Town lists per LDZ from energybrokers.co.uk (13 pages, fetched once; credited, not republished
   verbatim).
2. Each town is located with the ONS Index of Place Names (IPN, Open Government Licence) — no
   geocoding. Same-named places are resolved by the LDZ's listed counties, then by distance to the
   LDZ's other confidently placed towns.
3. Each local authority takes the LDZ its towns vote for. Authorities whose towns fall in more than
   one LDZ are marked split; inside them, places take the LDZ of the nearest labelled town (the old
   Voronoi idea, confined to the authority). Authorities with no listed town take the LDZ of the
   nearest labelled town to their centroid.
4. Review: towns the lists put in the wrong LDZ are corrected (town_corrections.csv), and a few
   authority decisions town votes can't make are set by hand (la_overrides.csv), both from the broker's
   own postcode search.

Outputs (committed, in geo/data/):
- ldz_towns.csv: each matched town — name, LDZ, IPN location, local authority, match method
- ldz_local_authority.csv: each local authority — LDZ (or split), vote shares, method, flags
- town_corrections.csv: towns listed under the wrong LDZ (applied after matching)
- la_overrides.csv: manual decisions for authorities after review (applied last)

Run:
    python -m ldz_demand.geo.ldz_membership fetch     # sources -> raw_dir/reference/
    python -m ldz_demand.geo.ldz_membership build     # raw sources -> geo/data/*.csv
"""

import argparse
import csv
import html
import io
import json
import logging
import math
import re
import sys
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

from ldz_demand.config import create_config, resolve_path
from ldz_demand.data.ingest.national_gas import LDZS

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
USER_AGENT = "ldz-demand/0.1 (research; one-off fetch)"
BROKER_URL = "https://www.energybrokers.co.uk/gas/gas-network/{code}-local-distribution-zone"
IPN_URL = "https://www.arcgis.com/sharing/rest/content/items/208d9884575647c29f0dd5a1184e711a/data"  # IPN July 2024
IPN_CSV = "IPN_GB_2024.csv"

# Place types used from the IPN, best first: built-up area, locality, parish/community, authority
PLACE_TYPES = {"BUA": 0, "LOC": 1, "PAR": 2, "COM": 2, "UA": 3, "NMD": 3, "MD": 3, "LONB": 3, "CA": 3}
AUTHORITY_TYPES = {"UA", "NMD", "MD", "LONB", "CA"}
SAME_PLACE_KM = 25      # IPN rows this close with the same name are one place (e.g. a BUA split across LAs)
FOOTPRINT_KM = 40       # a non-county match must lie this close to the LDZ's confident towns
CLEAR_MARGIN_KM = 20    # ...and be this much closer than the next candidate, if no other rule decides
SPLIT_SHARE = 0.8       # an authority is single-LDZ if one LDZ has at least this share of its votes
OUTLIER_KM = 40         # a town is an outlier if its nearest same-LDZ town is further than this...
OUTLIER_RATIO = 3       # ...and this many times further than the nearest town of another LDZ

# 2024 local authority recodes (IPN uses 2023 codes; DESNZ 2024 uses the new ones)
LAD_RECODES_2024 = {"E08000016": "E08000038", "E08000019": "E08000039"}  # Barnsley, Sheffield


# --- fetch -------------------------------------------------------------------------------------

def reference_dir(raw_dir: Path) -> Path:
    return Path(raw_dir) / "reference"


def fetch(raw_dir: Path, session: requests.Session | None = None, pause: float = 2.0) -> None:
    """Download the broker pages and the IPN once into raw_dir/reference/ (skips files present)."""
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    pages = reference_dir(raw_dir) / "energybrokers"
    pages.mkdir(parents=True, exist_ok=True)
    for ldz in LDZS:
        path = pages / f"{ldz.lower()}.html"
        if path.exists():
            continue
        response = session.get(BROKER_URL.format(code=ldz.lower()), timeout=60)
        response.raise_for_status()
        path.write_bytes(response.content)
        logger.info(f"Fetched broker page for {ldz}")
        time.sleep(pause)

    ipn_dir = reference_dir(raw_dir) / "ons_ipn"
    if not (ipn_dir / IPN_CSV).exists():
        ipn_dir.mkdir(parents=True, exist_ok=True)
        response = session.get(IPN_URL, timeout=600)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extract(IPN_CSV, ipn_dir)
        logger.info(f"Fetched ONS Index of Place Names -> {ipn_dir / IPN_CSV}")


# --- parse sources ------------------------------------------------------------------------------

def parse_broker_page(page: str) -> dict:
    """{'towns': [...], 'counties': [...]} from one LDZ page (one-column tables after each heading)."""
    def section(heading):
        m = re.search(rf"<p>\s*{heading}\s*</p>\s*<figure[^>]*>\s*<table[^>]*>(.*?)</table>", page, re.S)
        if not m:
            return []
        cells = re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)
        values = [html.unescape(re.sub(r"<[^>]+>", "", c)).replace("\xa0", " ").strip() for c in cells]
        return list(dict.fromkeys(v for v in values if v))
    return {"towns": section("Towns"), "counties": section("Counties")}


def load_broker_lists(raw_dir: Path) -> dict[str, dict]:
    pages = reference_dir(raw_dir) / "energybrokers"
    return {ldz: parse_broker_page((pages / f"{ldz.lower()}.html").read_text(encoding="utf-8", errors="replace"))
            for ldz in LDZS}


def load_ipn(raw_dir: Path) -> pd.DataFrame:
    raw = (reference_dir(raw_dir) / "ons_ipn" / IPN_CSV).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    ipn = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    ipn = ipn[ipn["descnm"].isin(PLACE_TYPES) & (ipn["lad23cd"] != "") & (ipn["lat"] != "")].copy()
    ipn["lat"], ipn["lon"] = ipn["lat"].astype(float), ipn["long"].astype(float)
    ipn["key"] = ipn["place23nm"].map(norm)
    return ipn


def load_county_corrections(path: Path = DATA_DIR / "county_corrections.csv") -> set[tuple[str, str]]:
    lines = [line for line in path.read_text().splitlines() if line and not line.startswith("#")]
    return {(r["ldz"], r["county"]) for r in csv.DictReader(lines)}


def load_town_corrections(path: Path = DATA_DIR / "town_corrections.csv") -> dict[tuple[str, str], str]:
    """{(listed ldz, town): correct ldz}."""
    lines = [line for line in path.read_text().splitlines() if line and not line.startswith("#")]
    return {(r["ldz"], r["town"]): r["correct_ldz"] for r in csv.DictReader(lines)}


def load_aliases(path: Path = DATA_DIR / "town_aliases.csv") -> dict[tuple[str, str], str]:
    lines = [line for line in path.read_text().splitlines() if line and not line.startswith("#")]
    return {(r["ldz"], r["town"]): r["ipn_name"] for r in csv.DictReader(lines)}


def norm(name: str) -> str:
    """Comparable form of a place name: ascii, lower case, 'saint' -> 'st', punctuation -> spaces."""
    name = name.replace("’", "").replace("'", "")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    name = name.replace("&", "and").replace("saint ", "st ").replace("st. ", "st ")
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


# --- match towns --------------------------------------------------------------------------------

@dataclass
class Place:
    """One real place: IPN rows sharing a name within SAME_PLACE_KM (may span local authorities)."""
    rows: list = field(default_factory=list)

    @property
    def centre(self) -> tuple[float, float]:
        best = min(self.rows, key=lambda r: PLACE_TYPES[r["descnm"]])
        return best["lat"], best["lon"]

    @property
    def lads(self) -> list[str]:
        return sorted({r["lad23cd"] for r in self.rows})

    @property
    def lad_names(self) -> list[str]:
        return sorted({r["lad23nm"] for r in self.rows})

    @property
    def best_type(self) -> int:
        return min(PLACE_TYPES[r["descnm"]] for r in self.rows)


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    x = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(x))


def group_places(rows: list[dict]) -> list[Place]:
    places: list[Place] = []
    for r in sorted(rows, key=lambda r: PLACE_TYPES[r["descnm"]]):
        for p in places:
            if km((r["lat"], r["lon"]), p.centre) <= SAME_PLACE_KM:
                p.rows.append(r)
                break
        else:
            places.append(Place([r]))
    return places


def _in_counties(place: Place, counties: list[str]) -> bool:
    fields = {norm(r[k]) for r in place.rows for k in ("ctyhistnm", "cty61nm", "cty91nm", "ctyltnm", "cty23nm", "lad23nm") if r[k]}
    return any(c in f or f in c for c in counties for f in fields)


def _named_after(place: Place, town: str) -> bool:
    """The place's local authority is named after the town (Luton in Luton, York in York...)."""
    t = norm(town)
    return any(norm(n) == t or norm(n).startswith(t + " ") or norm(n).endswith(" " + t) for n in place.lad_names)


def _pick(places: list[Place], town: str) -> Place | None:
    """Among plausible places, prefer the one named after the town, then the largest (built-up area)."""
    named = [p for p in places if _named_after(p, town)]
    if len(named) == 1:
        return named[0]
    pool = named or places
    best = min(p.best_type for p in pool)
    top = [p for p in pool if p.best_type == best]
    return top[0] if len(top) == 1 else None


def match_towns(lists: dict[str, dict], ipn: pd.DataFrame, aliases: dict | None = None,
                drop_counties: set[tuple[str, str]] | None = None) -> pd.DataFrame:
    """Locate every broker town in the IPN. Returns one row per (ldz, town) with method and location."""
    aliases = aliases or {}
    drop_counties = drop_counties or set()
    by_key = defaultdict(list)
    for r in ipn.to_dict("records"):
        by_key[r["key"]].append(r)

    county_keys = {ldz: [norm(c) for c in v["counties"] if (ldz, c) not in drop_counties] for ldz, v in lists.items()}
    candidates, chosen = {}, {}
    # pass 1: a single plausible place inside the LDZ's listed counties
    for ldz, v in lists.items():
        for town in v["towns"]:
            lookup = aliases.get((ldz, town), town)
            places = group_places(by_key.get(norm(lookup), []))
            candidates[(ldz, town)] = places
            in_cty = [p for p in places if _in_counties(p, county_keys[ldz])]
            pick = in_cty[0] if len(in_cty) == 1 else (_pick(in_cty, town) if in_cty else None)
            if pick:
                chosen[(ldz, town)] = (pick, "county", None)

    # pass 2: nearest plausible place to the LDZ's confidently placed towns
    footprint = defaultdict(list)
    for (ldz, _), (p, _, _) in chosen.items():
        footprint[ldz].append(p.centre)
    for (ldz, town), places in candidates.items():
        if (ldz, town) in chosen or not places or not footprint[ldz]:
            continue
        scored = sorted(((min(km(p.centre, f) for f in footprint[ldz]), p) for p in places), key=lambda x: x[0])
        near = [p for d, p in scored if d <= FOOTPRINT_KM]
        if not near:
            continue
        pick = near[0] if len(near) == 1 else _pick(near, town)
        if pick is None and len(scored) > 1 and scored[1][0] - scored[0][0] > CLEAR_MARGIN_KM:
            pick = scored[0][1]
        if pick:
            dist = next(d for d, p in scored if p is pick)
            chosen[(ldz, town)] = (pick, "footprint", round(dist, 1))

    outliers = _outliers({k: v[0].centre for k, v in chosen.items()})

    rows = []
    for (ldz, town), places in candidates.items():
        hit = chosen.get((ldz, town))
        if hit:
            p, method, dist = hit
            rows.append({"ldz": ldz, "town": town, "ipn_name": p.rows[0]["place23nm"], "lat": round(p.centre[0], 5),
                         "lon": round(p.centre[1], 5), "lad23cd": ";".join(p.lads), "lad23nm": ";".join(p.lad_names),
                         "method": ("outlier" if (ldz, town) in outliers else method) + ("+alias" if (ldz, town) in aliases else ""),
                         "footprint_km": dist})
        else:
            reason = "not_in_ipn" if not places else "ambiguous"
            rows.append({"ldz": ldz, "town": town, "ipn_name": None, "lat": None, "lon": None, "lad23cd": None,
                         "lad23nm": None, "method": reason, "footprint_km": None,
                         "candidates": "; ".join(f"{'/'.join(p.lad_names)}" for p in places[:4])})
    return pd.DataFrame(rows)


def _outliers(centres: dict[tuple[str, str], tuple[float, float]]) -> set[tuple[str, str]]:
    """
    Towns placed far from the rest of their LDZ but next to another LDZ's towns — usually errors in
    the source lists (e.g. an EM town found in Hampshire because the EM county list includes it).
    """
    items = list(centres.items())
    out = set()
    for (ldz, town), c in items:
        same = [km(c, c2) for (l2, t2), c2 in items if l2 == ldz and t2 != town]
        other = [km(c, c2) for (l2, _), c2 in items if l2 != ldz]
        if same and other and min(same) > OUTLIER_KM and min(same) > OUTLIER_RATIO * min(other):
            out.add((ldz, town))
    return out


def correct_towns(towns: pd.DataFrame, corrections: dict[tuple[str, str], str]) -> pd.DataFrame:
    """Move towns listed under the wrong LDZ to the right one (listed_ldz keeps the source's LDZ)."""
    out = towns.copy()
    out.insert(1, "listed_ldz", out["ldz"])
    keys = list(zip(out["ldz"], out["town"]))
    fix = [corrections.get(k) for k in keys]
    hit = [f is not None for f in fix]
    out.loc[hit, "ldz"] = [f for f in fix if f is not None]
    out.loc[hit, "method"] = out.loc[hit, "method"] + "+corrected"
    # a town already listed under its correct LDZ would otherwise vote twice
    return out.drop_duplicates(subset=["ldz", "town"]).reset_index(drop=True)


# --- local authorities --------------------------------------------------------------------------

def local_authorities(ipn: pd.DataFrame) -> pd.DataFrame:
    """All GB local authorities in the IPN with a centroid (from their own IPN authority row)."""
    lads = ipn[ipn["descnm"].isin(AUTHORITY_TYPES)].groupby("lad23cd").agg(
        lad23nm=("lad23nm", "first"), lat=("lat", "mean"), lon=("lon", "mean"), country=("ctry23nm", "first"))
    # authorities without their own row (rare): use the mean of their places
    others = ipn[~ipn["lad23cd"].isin(lads.index)].groupby("lad23cd").agg(
        lad23nm=("lad23nm", "first"), lat=("lat", "mean"), lon=("lon", "mean"), country=("ctry23nm", "first"))
    out = pd.concat([lads, others]).reset_index()
    out["lad24cd"] = out["lad23cd"].map(lambda c: LAD_RECODES_2024.get(c, c))
    return out


def assign_authorities(towns: pd.DataFrame, lads: pd.DataFrame, overrides: pd.DataFrame | None = None) -> pd.DataFrame:
    """LDZ per local authority from town votes; nearest labelled town for authorities with none."""
    matched = towns.dropna(subset=["lad23cd"])
    matched = matched[~matched["method"].str.startswith("outlier")]
    votes = defaultdict(Counter)
    for r in matched.itertuples():
        codes = r.lad23cd.split(";")
        for code in codes:
            votes[code][r.ldz] += 1 / len(codes)
    points = list(zip(matched["lat"], matched["lon"], matched["ldz"]))

    rows = []
    for la in lads.itertuples():
        v = votes.get(la.lad23cd)
        if v:
            total = sum(v.values())
            ldz, top = v.most_common(1)[0]
            share = top / total
            method = "unanimous" if share == 1 else ("majority" if share >= SPLIT_SHARE else "split")
            rows.append({"lad23cd": la.lad23cd, "lad24cd": la.lad24cd, "lad23nm": la.lad23nm, "country": la.country,
                         "ldz": ldz if method != "split" else "split", "main_ldz": ldz, "share": round(share, 3),
                         "votes": json.dumps({k: round(x, 2) for k, x in v.most_common()}), "n_towns": round(total, 2),
                         "method": method})
        else:
            d, ldz = min((km((la.lat, la.lon), (p[0], p[1])), p[2]) for p in points)
            rows.append({"lad23cd": la.lad23cd, "lad24cd": la.lad24cd, "lad23nm": la.lad23nm, "country": la.country,
                         "ldz": ldz, "main_ldz": ldz, "share": None, "votes": "{}", "n_towns": 0,
                         "method": f"nearest_town_{d:.0f}km"})
    out = pd.DataFrame(rows).sort_values(["country", "lad23nm"]).reset_index(drop=True)
    out["review"] = ""
    if overrides is not None and len(overrides):
        for o in overrides.itertuples():
            mask = out["lad23cd"] == o.lad23cd
            if o.ldz == "split":  # a confirmed split hidden by one LDZ's vote share: split by the votes
                out.loc[mask, ["ldz", "method"]] = ["split", "split"]
            else:
                out.loc[mask, ["ldz", "main_ldz", "share", "method"]] = [o.ldz, o.ldz, 1.0, f"override: {o.reason}"]
            out.loc[mask, "review"] = o.reason
    return out


def load_overrides(path: Path = DATA_DIR / "la_overrides.csv") -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["lad23cd", "ldz", "reason"])
    lines = [line for line in path.read_text().splitlines() if line and not line.startswith("#")]
    return pd.read_csv(io.StringIO("\n".join(lines)), dtype=str) if len(lines) > 1 else pd.DataFrame(columns=["lad23cd", "ldz", "reason"])


# --- build ---------------------------------------------------------------------------------------

HEADER = (
    "# Derived by ldz-demand (python -m ldz_demand.geo.ldz_membership build). Sources: town lists per LDZ from\n"
    "# energybrokers.co.uk (used as evidence, not republished verbatim); place locations and local authorities from\n"
    "# the ONS Index of Place Names, July 2024 (Open Government Licence v3.0). Reviewed against the same site's postcode\n"
    "# search (town_corrections.csv, la_overrides.csv). Not an official LDZ boundary.\n"
)


def build(raw_dir: Path, out_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    lists = load_broker_lists(raw_dir)
    ipn = load_ipn(raw_dir)
    towns = correct_towns(match_towns(lists, ipn, load_aliases(), load_county_corrections()), load_town_corrections())
    las = assign_authorities(towns, local_authorities(ipn), load_overrides())

    out_dir.mkdir(parents=True, exist_ok=True)
    town_cols = ["ldz", "listed_ldz", "town", "ipn_name", "lat", "lon", "lad23cd", "lad23nm", "method", "footprint_km"]
    for name, df, cols in (("ldz_towns.csv", towns, town_cols), ("ldz_local_authority.csv", las, list(las.columns))):
        with open(out_dir / name, "w", newline="") as f:
            f.write(HEADER)
            df[[c for c in cols if c in df.columns]].to_csv(f, index=False)
    _log_summary(towns, las)
    return towns, las


def _log_summary(towns: pd.DataFrame, las: pd.DataFrame) -> None:
    methods = towns["method"].str.split("+").str[0].value_counts().to_dict()
    logger.info(f"Towns: {len(towns)} — {methods}; {int(towns['method'].str.contains('corrected').sum())} corrected")
    la_methods = las["method"].str.replace(r"_\d+km$", "", regex=True).str.replace(r"^override:.*", "override", regex=True)
    la_methods = la_methods.value_counts().to_dict()
    logger.info(f"Local authorities: {len(las)} — {la_methods}")


def read_table(name: str) -> pd.DataFrame:
    """Load a committed reference table (skipping the comment header)."""
    return pd.read_csv(DATA_DIR / name, comment="#", dtype={"lad23cd": str, "lad24cd": str})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.geo.ldz_membership")
    parser.add_argument("command", choices=["fetch", "build"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    raw_dir = resolve_path(create_config(), "storage", "raw_dir")
    if args.command == "fetch":
        fetch(raw_dir)
    else:
        build(raw_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
