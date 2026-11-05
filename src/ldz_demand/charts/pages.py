"""
The dashboard's pages and the contents block shown on each of them.

Serve every page from one server (python -m ldz_demand.dashboard): the Overview (index.py, the
landing page: the live forecast and a short guide to the project) at /, and each page at its own path. The hosted copy is a static snapshot of the same pages
(python -m ldz_demand.publish), which sets SNAPSHOT_ENV so each page says so.
"""

import os
import subprocess
from dataclasses import dataclass
from datetime import date
from functools import cache

INDEX = "index.py"
SNAPSHOT_ENV = "LDZ_SNAPSHOT_DATE"  # set by publish: the date the hosted snapshot's data runs to
AUTHOR = "Robert Hemming"
REPO = "https://github.com/rwbh-lab/ldz-demand"


@dataclass(frozen=True)
class Page:
    section: str
    title: str
    path: str


PAGES = {  # file -> page, in reading order
    "summary.py": Page("Project", "Summary", "/summary"),
    "project_map.py": Page("Project", "Project map", "/project-map"),
    "ng_ldz_daily.py": Page("Datasets", "National Gas data", "/ng-ldz-daily"),
    "era5_weather.py": Page("Datasets", "ERA5 weather", "/era5-weather"),
    "ldz_geography.py": Page("Pre-CWV", "LDZ geography", "/ldz-geography"),
    "ldz_weather.py": Page("Pre-CWV", "LDZ weather", "/ldz-weather"),
    "ensemble_forecasts.py": Page("Pre-CWV", "LDZ Ens forecast", "/ensemble-forecasts"),
    "model_specification.py": Page("CWV model", "Model specification", "/model-specification"),
    "model_calibration.py": Page("CWV model", "Model calibration", "/model-calibration"),
    "backtesting_results.py": Page("Outputs", "Backtesting results", "/backtesting-results"),
    "live_forecasts.py": Page("Outputs", "Live forecasts", "/live-forecasts"),
}


def contents(current: str | None = None) -> dict[str, list[tuple[str, str | None]]]:
    """Section -> its pages as (title, path), in reading order, the overview first; the current page has no path."""
    sections: dict[str, list[tuple[str, str | None]]] = {"Project": [("Overview", None if current == INDEX else "/")]}
    for file, page in PAGES.items():
        sections.setdefault(page.section, []).append((page.title, None if file == current else page.path))
    return sections


def contents_html(current: str | None = None) -> str:
    """The contents as a two-column panel: sections down the left, each one's pages stacked in the right
    column; the current page in bold, marked with an accent bar, rather than linked. One line of HTML, so it
    can sit inside markdown."""
    from ldz_demand.charts import style

    accent = style.active().accent
    rows = []
    for section, links in contents(current).items():
        items = "".join(
            f'<a href="{path}">{title}</a>' if path is not None else
            f'<strong style="border-left: 2px solid {accent}; padding-left: 0.45em; margin-left: calc(-0.45em - 2px)">'
            f"{title}</strong>"
            for title, path in links)
        rows.append(f'<span style="color: var(--foreground); font-weight: 600; padding: 0.4em 2em 0.4em 0">{section}</span>'
                    f'<span style="display: flex; flex-direction: column; padding: 0.4em 0">{items}</span>')
    return ('<div style="display: grid; grid-template-columns: max-content max-content; width: fit-content; '
            'background: var(--muted); border-radius: 8px; padding: 0.5em 1.4em 0.5em 1.1em">'
            + "".join(rows) + "</div>")


def is_snapshot() -> bool:
    """True while publish exports the hosted snapshot (its controls are fixed)."""
    return bool(os.environ.get(SNAPSHOT_ENV))


def snapshot_note() -> str:
    """On the hosted snapshot, a line saying what it is; empty when served locally."""
    snapshot = os.environ.get(SNAPSHOT_ENV)
    if not snapshot:
        return ""
    return (f"*A static snapshot, with data to {snapshot}: the charts respond to hover and zoom, but the "
            "controls are fixed. Run the dashboard locally for the live version "
            "([README](https://github.com/rwbh-lab/ldz-demand#quick-start)).*")


@cache
def version() -> str:
    """The package version and, in a git checkout, the commit the pages were built from (e.g. "0.1.0 · 5afaa84")."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as package_version

    try:
        v = package_version("ldz-demand")
    except PackageNotFoundError:
        v = "dev"
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                             cwd=os.path.dirname(__file__)).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = ""
    return f"{v} · {sha}" if sha else v


def byline() -> str:
    """One line under each page title: who made it, how fresh the data is, and the version. On the hosted
    snapshot the data date is the snapshot's; served locally the pages read the database live."""
    snapshot = os.environ.get(SNAPSHOT_ENV)
    fresh = f"data to {snapshot} (static snapshot)" if snapshot else "live from the database"
    return (f'<div style="color: var(--muted-foreground); font-size: 0.85em">{AUTHOR} · {fresh} · '
            f'version {version()}</div>')


def footer():
    """The foot of every page: licence, code, how to cite it, and when the page was built."""
    import marimo as mo

    links = " · ".join([
        f'<a href="{REPO}">Code on GitHub</a>',
        f'<a href="{REPO}/blob/main/LICENSE">MIT licence</a>',
        f'<a href="{REPO}/blob/main/CITATION.cff">Cite this</a>',
        f'<a href="{REPO}/blob/main/docs/methodology.md">Methodology</a>',
        f'<a href="{REPO}#data-sources-and-licences">Data sources and licences</a>',
    ])
    return mo.Html(
        '<div style="border-top: 1px solid var(--border); margin-top: 2.5em; padding-top: 0.8em; '
        'color: var(--muted-foreground); font-size: 0.85em; display: flex; flex-wrap: wrap; gap: 0.3em 1.5em; '
        'justify-content: space-between">'
        f'<span>{links}</span>'
        f'<span>Built {date.today():%d %b %Y} · version {version()}</span></div>')


def tiles(items: list[tuple[str, str, str]]) -> str:
    """Headline numbers as compact tiles, (label, value, caption) each, in a grid that wraps to two or one
    columns on a narrow screen. HTML, so it can sit inside markdown or mo.Html."""
    cells = "".join(
        '<div style="border: 1px solid var(--border); border-radius: 8px; padding: 0.55em 0.85em">'
        f'<div style="color: var(--muted-foreground); font-size: 0.8em">{label}</div>'
        f'<div style="color: var(--foreground); font-size: 1.6em; font-weight: 600; line-height: 1.25; '
        f'font-variant-numeric: tabular-nums">{value}</div>'
        f'<div style="color: var(--muted-foreground); font-size: 0.8em">{caption}</div></div>'
        for label, value, caption in items)
    return ('<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(10.5em, 1fr)); gap: 0.6em">'
            + cells + "</div>")


def header(current: str, title, intro):
    """The head of a page: its title and one-line summary, then the contents panel beside the rest of the
    introduction (stacked when the window is narrow), then the snapshot note on the hosted copy."""
    import marimo as mo

    row = mo.Html(
        '<div style="display: flex; flex-wrap: wrap; align-items: flex-start; gap: 1.25em 2.5em">'
        f'<div style="flex: 0 0 auto">{contents_html(current)}</div>'
        f'<div style="flex: 1 1 22em; min-width: 0">{intro.text}</div></div>')
    note = snapshot_note()
    return mo.vstack([title, mo.Html(byline()), row] + ([mo.md(note)] if note else []), gap=0.75)
