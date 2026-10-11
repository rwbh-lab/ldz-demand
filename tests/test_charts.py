import pandas as pd
import plotly.io as pio
import pytest

from ldz_demand.charts import ng_ldz_daily as ng
from ldz_demand.charts import style
from ldz_demand.data.ingest.national_gas import LDZS


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


# --- National Gas chart data --------------------------------------------------------------------

def long_rows(day, ldz, total_mcm, dm_kwh, ndm_kwh, cv=36.0, uig_kwh=None, cwv=5.0):
    values = {"demand_total_d6": total_mcm, "demand_dm_d6": dm_kwh, "demand_ndm_d6": ndm_kwh,
              "cv": cv, "cwv_actual": cwv}
    if uig_kwh is not None:
        values["demand_uig_d6"] = uig_kwh
    return [{"gas_day": pd.Timestamp(day), "ldz": ldz, "item": k, "value": v} for k, v in values.items()]


@pytest.fixture
def raw():
    rows = []
    for ldz in LDZS:
        # 1 mcm at CV 36 = 10 GWh; DM 2 GWh + NDM 7 GWh -> gap 1 GWh
        rows += long_rows("2026-01-01", ldz, 1.0, 2e6, 7e6, uig_kwh=0.5e6)
        rows += long_rows("2026-01-02", ldz, 1.0, 2e6, 7e6, uig_kwh=0.5e6)
    rows = [r for r in rows if not (r["ldz"] == "SE" and r["gas_day"] == pd.Timestamp("2026-01-02") and r["item"] == "demand_total_d6")]
    rows += long_rows("2026-01-02", "SE", 0.5, 2e6, 7e6, uig_kwh=0.5e6)[:1]  # total 5 GWh vs parts 9 -> suspect
    return pd.DataFrame(rows)


def test_energy_frame_converts_units_and_derives_target(raw):
    e = ng.energy_frame(raw)
    ea = e.loc[(pd.Timestamp("2026-01-01"), "EA")]
    assert ea["total"] == pytest.approx(10.0)
    assert ea["dm"] == pytest.approx(2.0)
    assert ea["target"] == pytest.approx(8.0)
    assert ea["gap"] == pytest.approx(1.0)
    assert ea["residual"] == pytest.approx(0.5)
    assert ea["flag"] == "ok"


def test_flags_exclude_bad_totals_and_propagate_to_gb(raw):
    e = ng.energy_frame(raw)
    se = e.loc[(pd.Timestamp("2026-01-02"), "SE")]
    assert se["flag"] == "suspect"
    assert pd.isna(se["target"])

    gb = e.xs(ng.GB, level="ldz")
    assert gb.loc["2026-01-01", "total"] == pytest.approx(130.0)
    assert gb.loc["2026-01-01", "flag"] == "ok"
    assert gb.loc["2026-01-02", "flag"] == "suspect"
    assert pd.isna(gb.loc["2026-01-02", "target"])

    flagged = ng.flagged_days(e)
    assert flagged[["ldz", "reason"]].values.tolist() == [["SE", "suspect total"]]


def test_gas_years_run_october_to_september():
    assert list(ng._gas_year(pd.to_datetime(["2025-09-30", "2025-10-01", "2026-03-01"]))) == ["2024/25", "2025/26", "2025/26"]


def test_charts_build(raw):
    style.use()
    e = ng.energy_frame(raw)
    for fig in (ng.coverage(raw), ng.composition(e, "SE"), ng.gap(e, ng.GB, as_pct=True), ng.cwv_scatter(e, "SE", "2025/26")):
        assert fig.data
