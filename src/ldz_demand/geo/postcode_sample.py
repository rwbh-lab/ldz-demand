"""
Postcode-sampled LDZ shares for local authorities on an LDZ boundary.

The town lists say which LDZs meet inside an authority, but not how its gas divides between them:
the town votes count towns, and the Voronoi cells count area (Salisbury Plain weighs as much as
Swindon). Here the split is measured instead:

1. Sampling frame: every live GB postcode (OS Code-Point Open). A postcode covers roughly the same
   number of addresses wherever it is, so a simple random sample of an authority's postcodes is
   roughly a sample of its addresses — population-weighted, not area-weighted.
2. Authorities sampled: those whose towns vote for more than one LDZ (split or majority), where the
   network operators' checkers can tell the candidate LDZs apart.
3. Each sampled postcode goes to the network operators' own new-connection postcode checkers: SGN
   (operates SO, SE and SC) and Wales & West Utilities (SW, WS and WN). Cadent (EA, EM, NT, NW, WM)
   and Northern Gas Networks (NE, NO) have no comparable public checker, so a postcode neither
   checker claims is "other": it goes to the authority's remaining candidate LDZs, by their vote
   shares (one candidate, in practice, for most authorities).
4. The authority's share in each LDZ is the share of its resolved sample postcodes.

Caveats: a checker's "no" can also mean the postcode is missing from its list or off the gas network,
which leans "other" results towards the Cadent/NGN candidate; the unresolved rate where both
checkers are asked shows how often that happens. Business postcodes are in the frame too.

Run:
    python -m ldz_demand.geo.postcode_sample fetch    # Code-Point Open -> raw_dir/reference/
    python -m ldz_demand.geo.postcode_sample check    # sample + operator lookups (paced, resumable)
    python -m ldz_demand.geo.postcode_sample build    # cached answers -> geo/data/ldz_postcode_sample.csv
"""

import argparse
import hashlib
import json
import logging
import sys
import time
import zipfile
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

from ldz_demand.config import create_config, resolve_path
from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.geo.ldz_membership import DATA_DIR, USER_AGENT, read_table, reference_dir

logger = logging.getLogger(__name__)

CODEPOINT_LISTING = "https://api.os.uk/downloads/v1/products/CodePointOpen/downloads"
CODEPOINT_ZIP = "codepo_gb.zip"
SGN_URL = "https://www.sgn.co.uk/search_postcode"  # POST postcode=... -> "true"/"false"
WWU_URL = "https://www.wwutilities.co.uk/umbraco/api/PostcodeLookupApi/CheckService"  # GET ?postcode=

OPERATOR = {"SO": "SGN", "SE": "SGN", "SC": "SGN", "SW": "WWU", "WS": "WWU", "WN": "WWU",
            "EA": "Cadent", "EM": "Cadent", "NT": "Cadent", "NW": "Cadent", "WM": "Cadent", "NE": "NGN", "NO": "NGN"}
CHECKERS = ("SGN", "WWU")
SAMPLE_SIZE = 40        # postcodes per authority: about ±8 pp on a 50/50 split
MIN_RESOLVED = 15       # fewer resolved postcodes than this: fall back to the hybrid's shares
SEED = 2026
PAUSE = 1.0             # seconds between lookups on each operator's site
OUTPUT = "ldz_postcode_sample.csv"

HEADER = (
    "# Derived by ldz-demand (python -m ldz_demand.geo.postcode_sample build). Postcodes: OS Code-Point Open\n"
    "# (contains OS data © Crown copyright and database right; Royal Mail data © Royal Mail copyright and database\n"
    "# right; National Statistics data © Crown copyright and database right; Open Government Licence v3.0).\n"
    "# sgn / wwu: the answer of SGN's and Wales & West Utilities' new-connection postcode checkers (blank: not asked).\n"
    "# result: the LDZ the answers point to among the authority's candidates, 'other' (neither operator) or blank.\n"
)


# --- candidates and classification ----------------------------------------------------------------

def candidates(votes: dict) -> list[str]:
    """Candidate LDZs of an authority, in vote order."""
    return [z for z, _ in sorted(votes.items(), key=lambda kv: -kv[1])]


def resolvable(cands: list[str]) -> bool:
    """The checkers can tell the candidates apart: at least one is checkable, at most one per checker."""
    ops = [OPERATOR[z] for z in cands]
    return len(cands) > 1 and any(o in CHECKERS for o in ops) and all(ops.count(o) <= 1 for o in CHECKERS)


def checkers_needed(cands: list[str]) -> list[str]:
    return [o for o in CHECKERS if any(OPERATOR[z] == o for z in cands)]


def classify(cands: list[str], answers: dict[str, bool]) -> str | None:
    """The candidate LDZ the operator answers point to; 'other' if neither checker claims it; None if unresolved."""
    hits = [z for z in cands if OPERATOR[z] in CHECKERS and answers.get(OPERATOR[z])]
    if len(hits) == 1:
        return hits[0]
    if hits:
        return None  # two operators both claim it
    rest = [z for z in cands if OPERATOR[z] not in CHECKERS]
    return "other" if rest else None


def shares(cands: list[str], votes: dict, results: list) -> dict[str, float] | None:
    """LDZ shares from sampled results ('other' spread over the non-checkable candidates by vote)."""
    resolved = [r for r in results if isinstance(r, str) and r]
    if len(resolved) < MIN_RESOLVED:
        return None
    rest = [z for z in cands if OPERATOR[z] not in CHECKERS]
    rest_votes = sum(votes[z] for z in rest)
    out = dict.fromkeys(cands, 0.0)
    for r in resolved:
        if r == "other":
            for z in rest:
                out[z] += votes[z] / rest_votes
        else:
            out[r] += 1
    return {z: n / len(resolved) for z, n in out.items() if n > 0}


# --- sampling frame -------------------------------------------------------------------------------

def fetch(raw_dir: Path, session: requests.Session | None = None) -> None:
    """Download Code-Point Open (GB, CSV) into raw_dir/reference/os_codepoint/, checking its MD5."""
    path = reference_dir(raw_dir) / "os_codepoint" / CODEPOINT_ZIP
    if path.exists():
        return
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    item = next(i for i in session.get(CODEPOINT_LISTING, timeout=60).json() if i["format"] == "CSV" and i["area"] == "GB")
    response = session.get(item["url"], timeout=600)
    response.raise_for_status()
    if hashlib.md5(response.content).hexdigest() != item["md5"]:
        raise ValueError("Code-Point Open download failed its MD5 check")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    logger.info(f"Fetched Code-Point Open -> {path}")


def load_codepoint(raw_dir: Path) -> pd.DataFrame:
    """Live GB postcodes with a grid position: postcode, lad24cd, easting, northing."""
    cols = ["postcode", "quality", "easting", "northing", "country", "rh", "lh", "county", "lad24cd", "ward"]
    with zipfile.ZipFile(reference_dir(raw_dir) / "os_codepoint" / CODEPOINT_ZIP) as z:
        names = sorted(n for n in z.namelist() if n.startswith("Data/CSV/") and n.endswith(".csv"))
        df = pd.concat(pd.read_csv(z.open(n), header=None, names=cols, dtype=str,
                                   usecols=["postcode", "quality", "easting", "northing", "lad24cd"]) for n in names)
    df = df[(df["quality"] != "90") & df["lad24cd"].notna()]  # 90: no coordinates
    return df.drop(columns="quality").reset_index(drop=True)


def plan(las: pd.DataFrame, frame: pd.DataFrame, size: int = SAMPLE_SIZE, seed: int = SEED) -> pd.DataFrame:
    """The sample: `size` random postcodes in every resolvable multi-LDZ authority (reproducible)."""
    rows = []
    for la in las.itertuples():
        votes = json.loads(la.votes)
        cands = candidates(votes)
        if not resolvable(cands):
            continue
        pool = frame[frame["lad24cd"] == la.lad24cd].sort_values("postcode")
        pick = pool.sample(n=min(size, len(pool)), random_state=seed)
        for p in pick.itertuples():
            rows.append({"lad23cd": la.lad23cd, "lad24cd": la.lad24cd, "lad23nm": la.lad23nm, "candidates": "/".join(cands),
                         "postcode": p.postcode, "easting": int(p.easting), "northing": int(p.northing)})
    return pd.DataFrame(rows)


# --- operator lookups -----------------------------------------------------------------------------

def answers_path(raw_dir: Path) -> Path:
    return reference_dir(raw_dir) / "operator_checks" / "answers.csv"


def load_answers(raw_dir: Path) -> pd.DataFrame:
    path = answers_path(raw_dir)
    if not path.exists():
        return pd.DataFrame(columns=["postcode", "operator", "answer", "checked"])
    return pd.read_csv(path, dtype=str)


def ask(session: requests.Session, operator: str, postcode: str) -> bool:
    if operator == "SGN":
        r = session.post(SGN_URL, data={"postcode": postcode}, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
    else:
        r = session.get(WWU_URL, params={"postcode": postcode}, timeout=30)
    r.raise_for_status()
    text = r.text.strip().strip('"').lower()
    if text not in ("true", "false"):
        raise ValueError(f"{operator} returned {r.text[:80]!r} for {postcode}")
    return text == "true"


def check(raw_dir: Path, las: pd.DataFrame | None = None, session: requests.Session | None = None,
          pause: float = PAUSE) -> pd.DataFrame:
    """Ask the operators about every planned postcode not already answered (cached in raw_dir, resumable)."""
    las = read_table("ldz_local_authority.csv") if las is None else las
    sample = plan(las, load_codepoint(raw_dir))
    done = load_answers(raw_dir)
    seen = set(zip(done["postcode"], done["operator"]))
    todo = [(p, o) for p, c in zip(sample["postcode"], sample["candidates"])
            for o in checkers_needed(c.split("/")) if (p, o) not in seen]
    logger.info(f"{len(sample)} sampled postcodes in {sample['lad23cd'].nunique()} authorities; {len(todo)} lookups to do")
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    path = answers_path(raw_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    last = dict.fromkeys(CHECKERS, 0.0)
    with open(path, "a") as f:
        if write_header:
            f.write("postcode,operator,answer,checked\n")
        for i, (postcode, operator) in enumerate(todo, 1):
            time.sleep(max(0.0, pause - (time.monotonic() - last[operator])))
            answer = ask(session, operator, postcode)
            last[operator] = time.monotonic()
            f.write(f"{postcode},{operator},{str(answer).lower()},{date.today().isoformat()}\n")
            f.flush()
            if i % 100 == 0:
                logger.info(f"{i}/{len(todo)} lookups")
    return load_answers(raw_dir)


# --- build and use --------------------------------------------------------------------------------

def build(raw_dir: Path, out_dir: Path = DATA_DIR) -> pd.DataFrame | None:
    """Sample + cached answers -> the committed table (skipped, keeping the committed one, if no answers yet)."""
    if not answers_path(raw_dir).exists() or not (reference_dir(raw_dir) / "os_codepoint" / CODEPOINT_ZIP).exists():
        logger.info("No postcode sample answers yet (run: python -m ldz_demand.geo.postcode_sample check); skipped")
        return None
    from pyproj import Transformer

    sample = plan(read_table("ldz_local_authority.csv"), load_codepoint(raw_dir))
    ans = load_answers(raw_dir).drop_duplicates(subset=["postcode", "operator"], keep="last")
    lookup = {(p, o): a == "true" for p, o, a in zip(ans["postcode"], ans["operator"], ans["answer"])}
    for o in CHECKERS:
        sample[o.lower()] = [lookup.get((p, o)) for p in sample["postcode"]]
    sample["result"] = [classify(c.split("/"), {o: lookup.get((p, o)) for o in CHECKERS})
                        if all((p, o) in lookup for o in checkers_needed(c.split("/"))) else None
                        for p, c in zip(sample["postcode"], sample["candidates"])]
    lon, lat = Transformer.from_crs(27700, 4326, always_xy=True).transform(sample["easting"].to_numpy(), sample["northing"].to_numpy())
    sample["lat"], sample["lon"] = lat.round(5), lon.round(5)
    cols = ["lad23cd", "lad23nm", "candidates", "postcode", "lat", "lon", "sgn", "wwu", "result"]
    with open(out_dir / OUTPUT, "w", newline="") as f:
        f.write(HEADER)
        sample[cols].to_csv(f, index=False)
    resolved = sample["result"].notna().mean()
    logger.info(f"Postcode sample: {len(sample)} postcodes in {sample['lad23cd'].nunique()} authorities, {resolved:.0%} resolved")
    return sample


@lru_cache(maxsize=1)
def load() -> pd.DataFrame:
    """The committed sample (empty if not built yet)."""
    if not (DATA_DIR / OUTPUT).exists():
        return pd.DataFrame(columns=["lad23cd", "lad23nm", "candidates", "postcode", "lat", "lon", "sgn", "wwu", "result"])
    return read_table(OUTPUT)


def sampled_shares() -> dict[str, dict[str, float]]:
    """{lad23cd: {ldz: share}} for authorities with enough resolved sample postcodes."""
    las = read_table("ldz_local_authority.csv").set_index("lad23cd")
    out = {}
    for code, group in load().groupby("lad23cd"):
        if code not in las.index:
            continue
        votes = json.loads(las.loc[code, "votes"])
        s = shares(group["candidates"].iloc[0].split("/"), votes, group["result"].where(group["result"].notna(), None).tolist())
        if s:
            out[code] = s
    return out


@lru_cache(maxsize=1)
def authority_shares() -> pd.DataFrame:
    """Share of each local authority (rows: lad23cd) in each LDZ: the hybrid's, with sampled shares where measured."""
    from ldz_demand.geo import hybrid

    out = hybrid.authority_shares().copy()
    for code, s in sampled_shares().items():
        out.loc[code] = 0.0
        for z, w in s.items():
            out.loc[code, z] = w
    return out[list(LDZS)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.geo.postcode_sample")
    parser.add_argument("command", choices=["fetch", "check", "build"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    raw_dir = resolve_path(create_config(), "storage", "raw_dir")
    {"fetch": fetch, "check": check, "build": build}[args.command](raw_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
