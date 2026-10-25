"""
Publish the dashboard as a static snapshot for GitHub Pages (https://rwbh-lab.github.io/ldz-demand/).

    python -m ldz_demand.publish            # export every page into site/ (git-ignored)
    python -m ldz_demand.publish --push     # ... then push site/ to the gh-pages branch of the `github` remote

Each page is run once against the local data (marimo export html) and saved with its outputs: the Plotly
charts keep hover and zoom, but marimo's controls are fixed at their defaults. Each page says it is a
snapshot and the date its data runs to. Pages go to <path>/index.html, and links between them are rewritten
for the site's base path. The gh-pages branch holds only the latest snapshot (one commit, replaced each time).
"""

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ldz_demand.charts.pages import INDEX, PAGES, SNAPSHOT_ENV
from ldz_demand.config import get_project_root

logger = logging.getLogger(__name__)

BASE = "/ldz-demand"  # GitHub Pages serves the repo at <user>.github.io/<repo>/
REMOTE, BRANCH = "github", "gh-pages"
LINK = re.compile(r'(href=\\?")(/[a-z0-9-]*)(\\?")')  # as markdown links appear in the exported HTML
# never published: local paths (home folder, NAS share) and private network addresses
PRIVATE = re.compile(r"/Users/|/Volumes/|/volume\d/|\b192\.168\.\d|\b10\.\d+\.\d+\.\d+|\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d")


def snapshot_date() -> str:
    """The last gas day with published demand: what the snapshot's data runs to."""
    from ldz_demand.config import create_config
    from ldz_demand.data.datasets import NG_LDZ_DAILY
    from ldz_demand.data.store import get_store

    last = get_store(create_config()).last_date(NG_LDZ_DAILY)
    return last.strftime("%-d %B %Y") if last else "an unknown date"


def relink(html: str) -> str:
    """Links between pages ('/', '/live-forecasts') -> the site's paths ('/ldz-demand/', '/ldz-demand/live-forecasts/')."""
    paths = {"/"} | {page.path for page in PAGES.values()}

    def site_path(match: re.Match) -> str:
        path = match.group(2)
        if path not in paths:
            return match.group(0)
        return f"{match.group(1)}{BASE}{'/' if path == '/' else path + '/'}{match.group(3)}"

    return LINK.sub(site_path, html)


def export(notebook: Path, target: Path, env: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    run = subprocess.run(
        [sys.executable, "-m", "marimo", "export", "html", str(notebook), "-o", str(target), "--no-include-code", "-f"],
        env=env, capture_output=True, text=True,
    )
    if run.returncode != 0 or not target.exists():
        raise RuntimeError(f"Export of {notebook.name} failed:\n{run.stderr[-2000:]}")
    html = relink(target.read_text())
    if leak := PRIVATE.search(html):
        target.unlink()
        raise RuntimeError(f"{notebook.name}: the page shows a local path or address ({leak.group(0)!r}...), so it "
                           "isn't published. Usually a page that couldn't find its data (e.g. the NAS share not mounted).")
    target.write_text(html)
    logger.info(f"{notebook.name} -> {target} ({target.stat().st_size / 1e6:.1f} MB, {time.monotonic() - start:.0f} s)")


def build(out: Path) -> str:
    """Export every page into out/; returns the snapshot date."""
    date = snapshot_date()
    env = {**os.environ, SNAPSHOT_ENV: date}
    folder = get_project_root() / "dashboard"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    export(folder / INDEX, out / "index.html", env)
    for file, page in PAGES.items():
        export(folder / file, out / page.path.strip("/") / "index.html", env)
    (out / ".nojekyll").touch()  # serve the files as they are
    return date


def push(out: Path, date: str) -> None:
    """Replace the gh-pages branch with one commit holding out/, and push it."""
    root = get_project_root()
    with tempfile.TemporaryDirectory() as tmp:
        git = ["git", "-C", tmp]
        subprocess.run(["git", "init", "-q", "-b", BRANCH, tmp], check=True)
        shutil.copytree(out, tmp, dirs_exist_ok=True)
        subprocess.run([*git, "add", "-A"], check=True)
        email = subprocess.run(["git", "-C", str(root), "config", "user.email"], capture_output=True, text=True).stdout.strip()
        name = subprocess.run(["git", "-C", str(root), "config", "user.name"], capture_output=True, text=True).stdout.strip()
        subprocess.run([*git, "-c", f"user.email={email}", "-c", f"user.name={name}", "commit", "-q", "-m",
                        f"Dashboard snapshot, data to {date}"], check=True)
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", REMOTE], capture_output=True, text=True,
                             check=True).stdout.strip()
        subprocess.run([*git, "push", "--force", url, f"{BRANCH}:{BRANCH}"], check=True)
    logger.info(f"Pushed to {REMOTE}/{BRANCH}: https://rwbh-lab.github.io{BASE}/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.publish")
    parser.add_argument("--out", type=Path, default=get_project_root() / "site", help="where to write the site")
    parser.add_argument("--push", action="store_true", help=f"push the site to the {BRANCH} branch of `{REMOTE}`")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    date = build(args.out)
    size = sum(f.stat().st_size for f in args.out.rglob("*") if f.is_file()) / 1e6
    logger.info(f"Snapshot (data to {date}) in {args.out}: {size:.1f} MB")
    if args.push:
        push(args.out, date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
