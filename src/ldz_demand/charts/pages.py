"""
The dashboard's pages and the contents block shown on each of them.

Serve every page from one server (python -m ldz_demand.dashboard): the overview (index.py) at /,
and each page at its own path.
"""

from dataclasses import dataclass

INDEX = "index.py"


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


def nav(current: str):
    """The contents block for the head of a page, with a link back to the overview."""
    import marimo as mo

    return mo.md(f"[← Overview](/)  \n{contents_markdown(current)}")
