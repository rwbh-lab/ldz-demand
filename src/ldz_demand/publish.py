"""
Publish the dashboard as a static snapshot for GitHub Pages (https://rwbh-lab.github.io/ldz-demand/).

    python -m ldz_demand.publish            # export every page into deploy/site/ (git-ignored)
    python -m ldz_demand.publish --push     # ... then push deploy/site/ to the gh-pages branch of the `github` remote
    python -m ldz_demand.publish --push --if-configured   # the daily job: only where a push target is set

Each page is run once against the local data (marimo export html) and saved with its outputs: the Plotly
charts keep hover and zoom, but marimo's controls are fixed at their defaults. Each page says it is a
snapshot and the date its data runs to. Pages go to <path>/index.html, and links between them are rewritten
for the site's base path. The gh-pages branch holds only the latest snapshot (one commit, replaced each time).

Where it pushes: with LDZ_PUBLISH_TOKEN set (a fine-grained GitHub token with contents write on the repo; the
Docker image, which has no git checkout), to github.com/<LDZ_PUBLISH_REPO, default rwbh-lab/ldz-demand>. The
token goes to git in its environment, never in a command line or a log. Without it, to the `github` remote
of this checkout (the Mac). The commit author is LDZ_PUBLISH_NAME / LDZ_PUBLISH_EMAIL, else this checkout's
git user, else a generic name.

A page is refused (nothing is pushed) if its export fails (a cell raised), if it shows a local path or
address, or if it shows a warning callout: on these pages kind="warn" is kept for "the data is missing"
and setup help, which a published page must never be.
"""

import argparse
import base64
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
REPO = "rwbh-lab/ldz-demand"
TOKEN_ENV, REPO_ENV, NAME_ENV, EMAIL_ENV = "LDZ_PUBLISH_TOKEN", "LDZ_PUBLISH_REPO", "LDZ_PUBLISH_NAME", "LDZ_PUBLISH_EMAIL"
AUTHOR = ("ldz-demand daily job", "ldz-demand-job@users.noreply.github.com")
# a marimo callout of kind "warn", as it appears in the exported HTML (data-kind='&quot;warn&quot;', escaped)
WARN_CALLOUT = re.compile(r"data-kind=.{0,30}?warn")
LINK = re.compile(r'(href=\\?")(/[a-z0-9-]*)(\\?")')  # as markdown links appear in the exported HTML
# never published: local paths (home folder, mounted shares) and private network addresses
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
    run = subprocess.run(  # from the project root: marimo reads the theme from pyproject.toml in the cwd
        [sys.executable, "-m", "marimo", "export", "html", str(notebook), "-o", str(target), "--no-include-code", "-f"],
        env=env, capture_output=True, text=True, cwd=get_project_root(),
    )
    if run.returncode != 0 or not target.exists():
        raise RuntimeError(f"Export of {notebook.name} failed:\n{run.stderr[-2000:]}")
    html = relink(target.read_text())
    if leak := PRIVATE.search(html):
        target.unlink()
        raise RuntimeError(f"{notebook.name}: the page shows a local path or address ({leak.group(0)!r}...), so it "
                           "isn't published. Usually a page that couldn't find its data (e.g. a network share not mounted).")
    if WARN_CALLOUT.search(html):
        target.unlink()
        raise RuntimeError(f"{notebook.name}: the page shows a warning (on these pages: its data is missing, or "
                           "setup help), so it isn't published. Open it in the dashboard to see which.")
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


def push_target(env=None) -> tuple[str, dict[str, str]] | None:
    """
    (url, extra git environment) to push to, or None if nothing is set up. With a token, git gets it as an
    HTTP header through its environment (GIT_CONFIG_*), so it never appears in a command line, a log or an
    error; otherwise the checkout's `github` remote, with whatever credentials git already has.
    """
    env = os.environ if env is None else env
    if token := env.get(TOKEN_ENV, "").strip():
        repo = env.get(REPO_ENV, "").strip() or REPO
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return f"https://github.com/{repo}.git", {
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}", "GIT_TERMINAL_PROMPT": "0"}
    remote = _git_out("remote", "get-url", REMOTE)
    return (remote, {}) if remote else None


def author(env=None) -> tuple[str, str]:
    """(name, email) for the snapshot commit."""
    env = os.environ if env is None else env
    return (env.get(NAME_ENV) or _git_out("config", "user.name") or AUTHOR[0],
            env.get(EMAIL_ENV) or _git_out("config", "user.email") or AUTHOR[1])


def _git_out(*args: str) -> str:
    """A git query in the project root; '' if git or the checkout isn't there (the Docker image)."""
    try:
        run = subprocess.run(["git", "-C", str(get_project_root()), *args], capture_output=True, text=True)
    except FileNotFoundError:
        return ""
    return run.stdout.strip() if run.returncode == 0 else ""


def push(out: Path, date: str, target: tuple[str, dict[str, str]] | None = None) -> None:
    """Replace the gh-pages branch with one commit holding out/, and push it."""
    target = target or push_target()
    if target is None:
        raise RuntimeError(f"Nowhere to push: set {TOKEN_ENV}, or run from a checkout with a `{REMOTE}` remote.")
    url, git_env = target
    name, email = author()
    env = {**os.environ, **git_env}
    with tempfile.TemporaryDirectory() as tmp:
        git = ["git", "-C", tmp, "-c", f"user.name={name}", "-c", f"user.email={email}"]
        subprocess.run(["git", "init", "-q", "-b", BRANCH, tmp], check=True)
        shutil.copytree(out, tmp, dirs_exist_ok=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", f"Dashboard snapshot, data to {date}"], check=True)
        run = subprocess.run([*git, "push", "-q", "--force", url, f"{BRANCH}:{BRANCH}"], env=env,
                             capture_output=True, text=True)
        if run.returncode != 0:  # git's own message only: the token is in its environment, not in this text
            raise RuntimeError(f"Push to {url} failed (exit {run.returncode}): {run.stderr.strip()[-1000:]}")
    logger.info(f"Pushed to {url} {BRANCH}: https://rwbh-lab.github.io{BASE}/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ldz_demand.publish")
    parser.add_argument("--out", type=Path, default=get_project_root() / "deploy" / "site", help="where to write the site")
    parser.add_argument("--push", action="store_true", help=f"push the site to the {BRANCH} branch (see {TOKEN_ENV})")
    parser.add_argument("--if-configured", action="store_true",
                        help=f"with --push: do nothing (exit 0) where no push target is set up (no {TOKEN_ENV}, no "
                             f"`{REMOTE}` remote), so the daily job runs on any host")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    target = push_target() if args.push else None
    if args.push and target is None:
        if args.if_configured:
            logger.info(f"No push target ({TOKEN_ENV} not set, no `{REMOTE}` remote): not publishing")
            return 0
        logger.error(f"Nowhere to push: set {TOKEN_ENV}, or run from a checkout with a `{REMOTE}` remote")
        return 1
    date = build(args.out)
    size = sum(f.stat().st_size for f in args.out.rglob("*") if f.is_file()) / 1e6
    logger.info(f"Snapshot (data to {date}) in {args.out}: {size:.1f} MB")
    if args.push:
        push(args.out, date, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
