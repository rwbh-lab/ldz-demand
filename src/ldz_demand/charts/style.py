"""
Themes shared by the Plotly charts and the dashboard pages.

A Theme holds every colour and font. From one Theme we generate:
- a Plotly template (charts), via use()
- a CSS file for Marimo pages (page background, text, fonts), via write_css()

Switch theme for the dashboard with:
    python -m ldz_demand.charts.style claude_dark      # writes dashboard/theme.css
Pages read the active theme name back from that file, so charts and page always match.

Series colours are the validated categorical palette (colour-blind-safe in fixed order, >= 3:1
contrast on each theme's surface — checked with the dataviz validator). Use slots in order, never
cycle past 8; the first three are safe together on scatter plots.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THEME = "claude_dark"
SYSTEM_SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'


@dataclass(frozen=True)
class Theme:
    name: str
    mode: str          # "dark" | "light" — must match [tool.marimo.display] theme in pyproject.toml
    page: str          # page background
    surface: str       # chart / card background
    ink: str           # primary text, titles, the "total" line
    ink_2: str         # secondary text, legends
    muted: str         # axis labels, ticks, de-emphasised marks
    grid: str          # gridlines (hairline)
    axis: str          # axis lines / baselines
    border: str        # hairline borders around cards
    accent: str        # links and UI highlights only — not a data colour
    series: tuple[str, ...]      # categorical slots, in order
    sequential: tuple[str, ...]  # low -> high magnitude
    diverging: tuple[str, ...]   # cold pole -> neutral midpoint -> warm pole (odd length, grey middle)
    wind: tuple[str, ...]        # calm -> storm: multi-hue but monotonic in lightness (inferno-style)
    serious: str       # status colour for flagged data (always with a label)
    font: str = SYSTEM_SANS


_DARK_SERIES = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767")
_LIGHT_SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")
# blue ramp; dark themes run dark->bright so near-zero recedes into the surface
_DARK_SEQ = ("#104281", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef", "#b7d3f6")
_LIGHT_SEQ = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95")
# blue <-> red with a neutral grey midpoint, equal steps per arm
_DARK_DIV = ("#184f95", "#2a78d6", "#6da7ec", "#45443f", "#ec8a8a", "#e34948", "#a8302f")
_LIGHT_DIV = ("#184f95", "#3987e5", "#9ec5f4", "#f0efec", "#f3b0b0", "#e34948", "#a8302f")
# dark: calm recedes into the background, storms glow; light: the reverse (pale = calm)
_DARK_WIND = ("#1b0c41", "#4a0c6b", "#781c6d", "#a52c60", "#cf4446", "#ed6925", "#fb9b06", "#f7d13d")
_LIGHT_WIND = ("#fcfdbf", "#fec287", "#fc8961", "#e75263", "#b73779", "#822681", "#51127c", "#231151")

THEMES: dict[str, Theme] = {t.name: t for t in (
    # Warm charcoal in the spirit of the Claude desktop app (approximate, not official values)
    Theme("claude_dark", "dark",
          page="#1f1e1d", surface="#262624", ink="#faf9f5", ink_2="#c2c0b6", muted="#8f8d85",
          grid="#33322f", axis="#45443f", border="rgba(250,249,245,0.10)", accent="#d97757",
          series=_DARK_SERIES, sequential=_DARK_SEQ, diverging=_DARK_DIV, wind=_DARK_WIND, serious="#ec835a"),
    # Neutral near-black (the dataviz reference dark surfaces)
    Theme("neutral_dark", "dark",
          page="#0d0d0d", surface="#1a1a19", ink="#ffffff", ink_2="#c3c2b7", muted="#898781",
          grid="#2c2c2a", axis="#383835", border="rgba(255,255,255,0.10)", accent="#3987e5",
          series=_DARK_SERIES, sequential=_DARK_SEQ, diverging=_DARK_DIV, wind=_DARK_WIND, serious="#ec835a"),
    # Fallback if dark mode causes contrast trouble
    Theme("light", "light",
          page="#f9f9f7", surface="#fcfcfb", ink="#0b0b0b", ink_2="#52514e", muted="#898781",
          grid="#e1e0d9", axis="#c3c2b7", border="rgba(11,11,11,0.10)", accent="#2a78d6",
          series=_LIGHT_SERIES, sequential=_LIGHT_SEQ, diverging=_LIGHT_DIV, wind=_LIGHT_WIND, serious="#d0662f"),
)}

_active: Theme = THEMES[DEFAULT_THEME]


def active() -> Theme:
    """The theme charts are currently styled with."""
    return _active


def use(name: str | None = None) -> Theme:
    """Activate a theme for Plotly (registers template `ldz_<name>` and makes it the default)."""
    import plotly.io as pio

    global _active
    theme = THEMES[name or DEFAULT_THEME]
    pio.templates[f"ldz_{theme.name}"] = plotly_template(theme)
    pio.templates.default = f"ldz_{theme.name}"
    _active = theme
    return theme


TRANSPARENT_CHARTS = True  # charts sit on the page colour; False puts them on their own surface panel


def chart_bg(theme: Theme) -> str:
    """Background for chart paper, plot area and map frames."""
    return "rgba(0,0,0,0)" if TRANSPARENT_CHARTS else theme.surface


def plotly_template(theme: Theme):
    import plotly.graph_objects as go

    axis = dict(
        automargin=True,
        gridcolor=theme.grid, gridwidth=1, linecolor=theme.axis, zeroline=False, showline=True,
        ticks="outside", tickcolor=theme.axis, ticklen=4,
        tickfont=dict(color=theme.muted, size=12), title=dict(font=dict(color=theme.ink_2, size=13)),
    )
    return go.layout.Template(
        layout=dict(
            paper_bgcolor=chart_bg(theme),
            plot_bgcolor=chart_bg(theme),
            font=dict(family=theme.font, color=theme.ink_2, size=13),
            title=dict(font=dict(color=theme.ink, size=16), x=0, xanchor="left", pad=dict(l=4)),
            colorway=list(theme.series),
            xaxis=axis,
            yaxis=axis,
            # legend top-right, so the title and any range buttons keep the left side
            legend=dict(font=dict(color=theme.ink_2), bgcolor="rgba(0,0,0,0)", orientation="h",
                        yanchor="bottom", y=1.02, xanchor="right", x=1, traceorder="normal"),
            hoverlabel=dict(bgcolor=theme.page, bordercolor=theme.axis, font=dict(color=theme.ink, family=theme.font)),
            margin=dict(l=64, r=24, t=88, b=48),
            colorscale=dict(sequential=[[i / (len(theme.sequential) - 1), c] for i, c in enumerate(theme.sequential)]),
        ),
        data=dict(
            scatter=[go.Scatter(line=dict(width=2), marker=dict(size=8))],
            scattergl=[go.Scattergl(line=dict(width=2), marker=dict(size=8))],
        ),
    )


def css(theme: Theme) -> str:
    """Marimo page CSS for theme: overrides Marimo's colour and font variables."""
    tokens = {
        "--background": theme.page,
        "--foreground": theme.ink,
        "--muted": theme.surface,
        "--muted-foreground": theme.muted,
        "--card": theme.surface,
        "--card-foreground": theme.ink,
        "--popover": theme.surface,
        "--popover-foreground": theme.ink,
        "--border": theme.axis,
        "--input": theme.axis,
        "--marimo-text-font": theme.font,
        "--marimo-heading-font": theme.font,
    }
    body = "\n".join(f"  {k}: {v} !important;" for k, v in tokens.items())
    return f"""/* theme: {theme.name} — generated by `python -m ldz_demand.charts.style {theme.name}`; do not edit */
:root, .dark, .dark-theme {{
{body}
}}
body, #App {{ background: {theme.page} !important; color: {theme.ink}; }}
.markdown a, a, .markdown a:visited, a:visited {{ color: {theme.accent} !important; }}
.markdown h1, .markdown h2, .markdown h3 {{ color: {theme.ink}; font-weight: 600; letter-spacing: -0.01em; }}
.markdown p, .markdown li {{ color: {theme.ink_2}; }}
.markdown table th, .markdown table td {{ text-align: left !important; }}
"""


def write_css(name: str, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(css(THEMES[name]))
    return path


def theme_name_from_css(path: Path) -> str:
    """Theme name recorded in a generated CSS file; the default if the file is missing."""
    try:
        match = re.search(r"/\* theme: (\w+)", Path(path).read_text())
    except FileNotFoundError:
        return DEFAULT_THEME
    return match.group(1) if match and match.group(1) in THEMES else DEFAULT_THEME


def main(argv: list[str] | None = None) -> int:
    from ldz_demand.config import get_project_root

    parser = argparse.ArgumentParser(prog="python -m ldz_demand.charts.style", description="Set the dashboard theme.")
    parser.add_argument("theme", choices=sorted(THEMES))
    parser.add_argument("--out", type=Path, default=get_project_root() / "dashboard" / "theme.css")
    args = parser.parse_args(argv)

    path = write_css(args.theme, args.out)
    theme = THEMES[args.theme]
    print(f"Wrote {path} ({theme.name}, {theme.mode} mode). Reload the dashboard page to apply.")
    print(f'Marimo widgets follow [tool.marimo.display] theme in pyproject.toml — set it to "{theme.mode}".')
    return 0


if __name__ == "__main__":
    sys.exit(main())
