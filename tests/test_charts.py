import pandas as pd
import plotly.io as pio
import pytest

from ldz_demand.charts import ng_ldz_daily as ng
from ldz_demand.charts import style


# --- theme --------------------------------------------------------------------------------------

def test_use_registers_and_activates_template():
    theme = style.use("light")
    assert pio.templates.default == "ldz_light"
    assert style.active() is theme
    assert list(pio.templates["ldz_light"].layout.colorway) == list(theme.series)
    style.use()  # back to default
    assert style.active().name == style.DEFAULT_THEME


def test_css_round_trips_theme_name(tmp_path):
    path = style.write_css("neutral_dark", tmp_path / "theme.css")
    text = path.read_text()
    assert "--background: #0d0d0d" in text
    assert style.theme_name_from_css(path) == "neutral_dark"
    assert style.theme_name_from_css(tmp_path / "missing.css") == style.DEFAULT_THEME


def test_themes_have_eight_series_and_matching_modes():
    for theme in style.THEMES.values():
        assert len(theme.series) == 8
        assert theme.mode in ("dark", "light")


# --- National Gas charts -----------------------------------------------------------------------

def test_charts_build():
    from test_ldz_energy import offtake_rows, raw_rows

    from ldz_demand.data import ldz_energy as le

    style.use()
    raw = raw_rows()
    e = le.energy_frame(raw, offtake_rows())
    for fig in (ng.coverage(raw), ng.composition(e, "SE"), ng.gap(e, le.GB, as_pct=True),
                ng.cwv_scatter(e, "SE", "2025/26", target="target_repaired"), ng.feed_check(e, "SE"),
                ng.offtake_share(e)):
        assert fig.data


def test_no_plotly_formats_with_a_plus_sign():
    """Plotly.js 3 (as shipped with marimo) ignores d3 formats with a '+' flag in hover / text templates,
    showing the raw number; format in Python instead (e.g. f"{v:+.2f}") when a sign is wanted."""
    import re
    from pathlib import Path

    charts = Path(__file__).parent.parent / "src" / "ldz_demand" / "charts"
    hits = [f"{p.name}: {m}" for p in charts.glob("*.py") for m in re.findall(r"%\{\{?[^}]*:\+[^}]*\}", p.read_text())]
    assert not hits, hits
