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
    "ng_ldz_daily.py": Page("Data", "National Gas data", "/ng-ldz-daily"),
    "era5_weather.py": Page("Data", "ERA5 weather", "/era5-weather"),
    "ldz_geography.py": Page("Pre-CWV models", "LDZ geography", "/ldz-geography"),
    "ldz_weather.py": Page("Pre-CWV models", "LDZ weather", "/ldz-weather"),
    "ensemble_forecasts.py": Page("Pre-CWV models", "Ensemble LDZ weather", "/ensemble-forecasts"),
    "demand_model.py": Page("CWV model", "Demand model", "/demand-model"),
    "results.py": Page("Outputs", "Results", "/results"),
    "demand_forecasts.py": Page("Outputs", "Demand forecasts", "/demand-forecasts"),
}


def contents_markdown(current: str | None = None) -> str:
    """One line per section ('Data: A | B'), the current page in bold rather than linked."""
    sections: dict[str, list[str]] = {}
    for file, page in PAGES.items():
        sections.setdefault(page.section, []).append(f"**{page.title}**" if file == current else f"[{page.title}]({page.path})")
    return "  \n".join(f"{section}: " + " | ".join(links) for section, links in sections.items())


def snapshot_note() -> str:
    """On the hosted snapshot, a line saying what it is; empty when served locally."""
    snapshot = os.environ.get(SNAPSHOT_ENV)
    if not snapshot:
        return ""
    return (f"*A static snapshot, with data to {snapshot}: the charts respond to hover and zoom, but the "
            "controls are fixed. Run the dashboard locally for the live version "
            "([README](https://github.com/rwbh-lab/ldz-demand#quick-start)).*")


def nav(current: str):
    """The contents block for the head of a page, with a link back to the overview."""
    import marimo as mo

    note = snapshot_note()
    return mo.md(f"[← Overview](/)  \n{contents_markdown(current)}" + (f"\n\n{note}" if note else ""))
