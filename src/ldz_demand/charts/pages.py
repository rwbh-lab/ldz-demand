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


LATEST_RUN_TTL_S = 300  # the live server asks the database again after this long
_latest_run: tuple[float, str | None] = (0.0, None)


def latest_run() -> str | None:
    """When the latest forecast was written, UK time ("05 Nov 10:50"): MySQL's last write to
    demand_forecast_daily, which the daily job makes as its last step. That time is lost when MySQL restarts,
    and the CSV store has none, so then just the latest run's date. None if no forecast can be read."""
    global _latest_run
    import time

    checked, value = _latest_run
    if time.monotonic() - checked < LATEST_RUN_TTL_S and value:
        return value
    try:
        from ldz_demand.config import create_config
        from ldz_demand.data.datasets import DEMAND_FORECAST_DAILY
        from ldz_demand.data.store import get_store

        store = get_store(create_config())
        written = None
        if engine := getattr(store, "engine", None):
            import sqlalchemy as sa

            with engine.connect() as conn:
                written = conn.execute(sa.text(
                    "SELECT UPDATE_TIME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = :t"), {"t": DEMAND_FORECAST_DAILY.name}).scalar()
        if written is not None:  # the server keeps UTC
            from zoneinfo import ZoneInfo

            uk = written.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/London"))
            value = f"{uk:%d %b %H:%M}"
        else:
            last = store.last_date(DEMAND_FORECAST_DAILY)
            value = f"{last:%d %b}" if last else None
    except Exception:  # the byline must never break a page
        value = None
    _latest_run = (time.monotonic(), value)
    return value


def byline() -> str:
    """One line under each page title: who made it, how fresh the data is, and the version. "live" when the
    pages read the database as they are served, "static" on the hosted snapshot (built by publish), each with
    the time of the latest forecast run."""
    run = latest_run()
    fresh = ("static" if os.environ.get(SNAPSHOT_ENV) else "live") + (f" · latest run {run}" if run else "")
    return (f'<div style="color: var(--muted-foreground); font-size: 0.85em">{AUTHOR} · {fresh} · '
            f'version {version()}</div>')


def footer(definitions: bool = False):
    """The foot of every page: licence, code, how to cite it, and when the page was built. definitions: the
    page uses the notation, so its definitions go above the links (the target of define()'s link)."""
    import marimo as mo

    links = " · ".join([
        f'<a href="{REPO}">Code on GitHub</a>',
        f'<a href="{REPO}/blob/main/LICENSE">MIT licence</a>',
        f'<a href="{REPO}/blob/main/CITATION.cff">Cite this</a>',
        f'<a href="{REPO}/blob/main/docs/methodology.md">Methodology</a>',
        f'<a href="{REPO}#data-sources-and-licences">Data sources and licences</a>',
    ])
    return mo.Html((definitions_html() if definitions else "") +
        '<div style="border-top: 1px solid var(--border); margin-top: 2.5em; padding-top: 0.8em; '
        'color: var(--muted-foreground); font-size: 0.85em; display: flex; flex-wrap: wrap; gap: 0.3em 1.5em; '
        'justify-content: space-between">'
        f'<span>{links}</span>'
        f'<span>Built {date.today():%d %b %Y} · version {version()}</span></div>')


# Notation, HTML so the same symbols work in markdown, tiles and Plotly text. D is the gas day (D+1, D+6 are
# National Gas's publication lags), so demand takes Q. A page that uses them links to its definitions near the
# top (define()) and lists them at the foot (footer(definitions=True)).
Q = "<i>Q</i>"


def P(q: int) -> str:
    """A forecast quantile of Q: P(10) -> P₁₀."""
    return f"P<sub>{q}</sub>"


def Q_at(lag: int) -> str:
    """Published demand as it stood lag days after the gas day: Q_at(6) -> Q_D+6 (closed out)."""
    return f"{Q}<sub>D+{lag}</sub>"


P_RANGE = f"{P(10)}–{P(90)}"


DEFINITIONS_ID = "definitions"
DEFINITIONS = (
    (Q, "gas demand: LDZ total minus daily-metered, GWh per gas day"),
    (P_RANGE, f"the forecast range {Q} falls in 8 times in 10; {P(50)} is the median"),
    (f"{Q_at(1)}, {Q_at(6)}", "National Gas's provisional (next day) and closed-out (six days on) figures"),
)


def define() -> str:
    """Near the top of a page that uses the notation: a link to its definitions at the foot."""
    return (f'<div style="font-size: 0.85em"><a href="#{DEFINITIONS_ID}"><i>Definitions</i></a></div>')


def definitions_html() -> str:
    """The notation, a term per line, at the foot of the page (define() links here)."""
    rows = "".join(f'<div><span style="color: var(--foreground)">{term}</span> — {meaning}</div>'
                   for term, meaning in DEFINITIONS)
    return (f'<div id="{DEFINITIONS_ID}" style="margin-top: 2.5em; color: var(--muted-foreground); font-size: 0.9em; '
            f'line-height: 1.7"><div style="font-weight: 600; color: var(--foreground)"><i>Definitions</i></div>{rows}</div>')


def heading(label: str, statement: str, level: int = 2) -> str:
    """A section heading as markdown: a muted label, a bar, then the takeaway, e.g. "Results | 9% below the
    official CWV". The label says where you are; the statement says what the section shows."""
    return (f'{"#" * level} <span style="color: var(--muted-foreground); font-weight: 400">{label} |</span> '
            f'{statement}')


def tiles(items: list[tuple[str, str, str] | tuple[str, str, str, str]]) -> str:
    """Headline numbers as compact tiles, (label, value, caption) or (label, value, caption, unit) each, in
    a grid that wraps to two or one columns on a narrow screen. A unit sits after the value, smaller and
    muted. HTML, so it can sit inside markdown or mo.Html."""
    def _cell(label, value, caption, unit=""):
        unit_html = (f' <span style="color: var(--muted-foreground); font-size: 0.55em; font-weight: 400">'
                     f'{unit}</span>') if unit else ""
        return ('<div style="border: 1px solid var(--border); border-radius: 8px; padding: 0.55em 0.85em">'
                f'<div style="color: var(--muted-foreground); font-size: 0.8em">{label}</div>'
                f'<div style="color: var(--foreground); font-size: 1.6em; font-weight: 600; line-height: 1.25; '
                f'font-variant-numeric: tabular-nums">{value}{unit_html}</div>'
                f'<div style="color: var(--muted-foreground); font-size: 0.8em">{caption}</div></div>')

    cells = "".join(_cell(*item) for item in items)
    return ('<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(10.5em, 1fr)); gap: 0.6em">'
            + cells + "</div>")


def header(current: str, title, intro, notation: bool = False):
    """The head of a page: its title and one-line summary, then the contents panel beside the rest of the
    introduction (stacked when the window is narrow), then the snapshot note on the hosted copy. notation: the page uses Q and P₁₀–P₉₀, so define them
    under the byline."""
    import marimo as mo

    row = mo.Html(
        '<div style="display: flex; flex-wrap: wrap; align-items: flex-start; gap: 1.25em 2.5em">'
        f'<div style="flex: 0 0 auto">{contents_html(current)}</div>'
        f'<div style="flex: 1 1 22em; min-width: 0">{intro.text}</div></div>')
    note = snapshot_note()
    head = [title, mo.Html(byline())] + ([mo.Html(define())] if notation else [])
    return mo.vstack(head + [row] + ([mo.md(note)] if note else []), gap=0.75)
