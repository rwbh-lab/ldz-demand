import re

import pandas as pd
import pytest

from ldz_demand.charts import overview as ov
from ldz_demand.models import results


def test_headline_reads_the_final_model_against_the_official_cwv():
    h = ov.headline(results.load("experiments"))
    assert h.cold < h.winter < 0 and h.all_days < 0     # better, and most of all on cold days
    assert h.ldz_count == 13 and 0 < h.ldz_better <= 13 and h.days > 0


def test_live_record_counts_runs_coverage_and_the_lead_one_error():
    days = pd.date_range("2026-10-13", periods=3)
    runs = pd.DataFrame({"run_date": [days[0], days[0], days[1]], "ldz": "GB",
                         "gas_day": [days[0], days[1], days[2]], "lead_days": [0, 1, 1],
                         "p10": 90.0, "p50": 100.0, "p90": 110.0, "weather_p10": 95.0, "weather_p90": 105.0})
    actual = pd.DataFrame({"gas_day": days, "ldz": "GB", "actual": [100.0, 125.0, 95.0], "provisional": False})
    r = ov.live_record(runs, actual)
    assert (r.runs, r.days, r.first_run) == (2, 3, days[0])
    assert r.coverage == pytest.approx(200 / 3)           # 125 is outside 90-110
    assert r.lead1_error == pytest.approx((20 + 100 / 95 * 5) / 2, rel=1e-3)
    assert ov.live_record(runs, actual.iloc[:0]) is None


def _run(medians):
    days = pd.date_range("2026-11-05", periods=len(medians))
    m = pd.Series(medians, dtype=float)
    return pd.DataFrame({"run_date": pd.Timestamp("2026-11-04"), "ldz": "GB", "gas_day": days,
                         "lead_days": range(1, len(medians) + 1), "p10": m * 0.9, "p50": m, "p90": m * 1.1})


@pytest.mark.parametrize("medians, start", [
    ([1000, 1050, 1200, 1100], "Demand climbs about 20% to a peak on Sat 07 Nov"),
    ([1000, 950, 900, 920], "Demand eases about 10% by Sat 07 Nov"),
    ([1000, 1020, 990, 1010], "Demand holds near 1,000 GWh/day"),
])
def test_the_outlook_says_which_way_demand_goes(medians, start):
    o = ov.outlook(_run(medians))
    assert o.takeaway.startswith(start)
    assert o.tomorrow["p50"] == medians[0] and o.peak["p50"] == max(medians) and o.low["p50"] == min(medians)
    assert o.spread_tomorrow == pytest.approx(10)


def test_byline_footer_and_tiles_render():
    from ldz_demand.charts import pages

    assert "Robert Hemming" in pages.byline() and "version" in pages.byline()
    html = pages.footer().text
    assert "LICENSE" in html and "CITATION.cff" in html and "Built" in html
    tiles = pages.tiles([("Tomorrow", "1,400", "10–90% 1,300–1,500", "GWh/day"), ("Range", "±5%", "half")])
    assert tiles.count("1,400") == 1 and "auto-fit" in tiles
    value_lines = re.findall(r'font-size: 1\.6em[^>]*>(.*?)</div>', tiles)
    assert value_lines[0].startswith("1,400 <span") and "GWh/day</span>" in value_lines[0]
    assert value_lines[1] == "±5%" and tiles.count("GWh/day") == 1    # no unit given, none shown


def test_pages_using_the_notation_define_it():
    """Q and P10-P90 are introduced once on every page that shows them (the forecast charts use them)."""
    from pathlib import Path

    uses = ("fch.", "P_RANGE", "pages.Q", "<i>Q</i>", "Q_at(")
    for page in sorted((Path(__file__).parents[1] / "dashboard").glob("*.py")):
        src = page.read_text()
        if any(u in src for u in uses):
            assert "define()" in src or "notation=True" in src, f"{page.name} uses Q without linking its definitions"
            assert "footer(definitions=True)" in src, f"{page.name} uses Q without definitions at the foot"


def test_byline_says_live_or_static_with_the_latest_run(monkeypatch):
    from ldz_demand.charts import pages

    monkeypatch.setattr(pages, "latest_run", lambda: "05 Nov 10:50")
    monkeypatch.delenv(pages.SNAPSHOT_ENV, raising=False)
    assert "live · latest run 05 Nov 10:50" in pages.byline()
    monkeypatch.setenv(pages.SNAPSHOT_ENV, "3 November 2026")
    assert "static · latest run 05 Nov 10:50" in pages.byline()
    monkeypatch.setattr(pages, "latest_run", lambda: None)  # nothing readable: just the mode
    assert "static · version" in pages.byline()
