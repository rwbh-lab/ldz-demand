"""
The dashboard's pages and the contents block shown on each of them.

Serve every page from one server (python -m ldz_demand.dashboard): the overview (index.py) at /,
and each page at its own path. The hosted copy is a static snapshot of the same pages
(python -m ldz_demand.publish), which sets SNAPSHOT_ENV so each page says so.
"""

import os
from dataclasses import dataclass

INDEX = "index.py"
SNAPSHOT_ENV = "LDZ_SNAPSHOT_DATE"  # set by publish: the date the hosted snapshot's data runs to


@dataclass(frozen=True)
class Page:
    section: str
    title: str
    path: str


PAGES = {  # file -> page, in reading order
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


def snapshot_note() -> str:
    """On the hosted snapshot, a line saying what it is; empty when served locally."""
    snapshot = os.environ.get(SNAPSHOT_ENV)
    if not snapshot:
        return ""
    return (f"*A static snapshot, with data to {snapshot}: the charts respond to hover and zoom, but the "
            "controls are fixed. Run the dashboard locally for the live version "
            "([README](https://github.com/rwbh-lab/ldz-demand#quick-start)).*")


def header(current: str, title, intro):
    """The head of a page: its title and one-line summary, then the contents panel beside the rest of the
    introduction (stacked when the window is narrow), then the snapshot note on the hosted copy."""
    import marimo as mo

    row = mo.Html(
        '<div style="display: flex; flex-wrap: wrap; align-items: flex-start; gap: 1.25em 2.5em">'
        f'<div style="flex: 0 0 auto">{contents_html(current)}</div>'
        f'<div style="flex: 1 1 22em; min-width: 0">{intro.text}</div></div>')
    note = snapshot_note()
    return mo.vstack([title, row] + ([mo.md(note)] if note else []), gap=0.75)
