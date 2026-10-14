import pandas as pd
import pytest

from ldz_demand.data import ldz_energy as le
from ldz_demand.data.ingest.national_gas import LDZS

DAYS = ["2026-01-01", "2026-01-02", "2026-01-03"]


def long_rows(day, ldz, total_mcm, dm_kwh=2e6, ndm_kwh=7e6, cv=36.0, uig_kwh=0.5e6, cwv=5.0):
    values = {"demand_total_d6": total_mcm, "demand_dm_d6": dm_kwh, "demand_ndm_d6": ndm_kwh,
              "demand_uig_d6": uig_kwh, "cv": cv, "cwv_actual": cwv}
    return [{"gas_day": pd.Timestamp(day), "ldz": ldz, "item": k, "value": v} for k, v in values.items()]


def raw_rows(se_total_day2=1.0):
    """1 mcm at CV 36 = 10 GWh; DM 2 + NDM 7 GWh -> gap 1 GWh. SE day 2 total configurable."""
    rows = []
    for ldz in LDZS:
        for day in DAYS:
            total = se_total_day2 if (ldz == "SE" and day == DAYS[1]) else 1.0
            rows += long_rows(day, ldz, total)
    return pd.DataFrame(rows)


def offtake_rows(se_missing_feed_day2=True):
    """Offtakes: 10 GWh everywhere, except SE gets 7 GWh from NTS + a 3 GWh non-NTS feed (usual)."""
    rows = []
    for ldz in LDZS:
        for day in DAYS:
            gwh = 7.0 if ldz == "SE" else 10.0
            rows.append({"gas_day": pd.Timestamp(day), "ldz": ldz, "site": "A", "value": gwh * 1e6})
    return pd.DataFrame(rows)


def test_units_and_target():
    e = le.energy_frame(raw_rows())
    ea = e.loc[(pd.Timestamp(DAYS[0]), "EA")]
    assert ea["total"] == pytest.approx(10.0)
    assert ea["target"] == pytest.approx(8.0)
    assert ea["gap"] == pytest.approx(1.0)
    assert ea["residual"] == pytest.approx(0.5)
    assert ea["flag"] == "ok"


def test_ratio_rule_without_offtakes():
    e = le.energy_frame(raw_rows(se_total_day2=0.5))  # 5 GWh vs parts 9 -> ratio 0.56
    se = e.loc[(pd.Timestamp(DAYS[1]), "SE")]
    assert se["flag"] == "suspect"
    assert pd.isna(se["target"]) and pd.isna(se["target_repaired"])
    assert e.loc[(pd.Timestamp(DAYS[1]), le.GB), "flag"] == "suspect"


def test_missing_feed_is_flagged_and_repaired(monkeypatch):
    # SE usual non-NTS input is 3 GWh; on day 2 the published total drops to the offtakes alone (7 GWh)
    monkeypatch.setattr(le, "FEED_MATERIAL", 2.0)
    e = le.energy_frame(raw_rows(se_total_day2=0.7), offtake_rows())
    se = e.loc[(pd.Timestamp(DAYS[1]), "SE")]
    assert se["other"] == pytest.approx(0.0)
    assert se["other_usual"] == pytest.approx(3.0)
    assert se["flag"] == "missing_feed"
    assert pd.isna(se["target"])                                 # option A: excluded
    assert se["total_repaired"] == pytest.approx(10.0)           # offtakes 7 + usual 3
    assert se["target_repaired"] == pytest.approx(8.0)           # option B: repaired

    gb = e.xs(le.GB, level="ldz")
    assert gb.loc[DAYS[1], "flag"] == "missing_feed"
    assert pd.isna(gb.loc[DAYS[1], "target"])
    assert gb.loc[DAYS[1], "target_repaired"] == pytest.approx(13 * 8.0)
    assert gb.loc[DAYS[0], "flag"] == "ok"


def test_mismatch_and_invalid():
    off = offtake_rows()
    off.loc[(off.ldz == "EA") & (off.gas_day == pd.Timestamp(DAYS[2])), "value"] = 30e6  # offtakes 3x the total
    raw = raw_rows(se_total_day2=-0.01)
    e = le.energy_frame(raw, off)
    assert e.loc[(pd.Timestamp(DAYS[2]), "EA"), "flag"] == "mismatch"
    assert e.loc[(pd.Timestamp(DAYS[1]), "SE"), "flag"] == "invalid"

    flagged = le.flagged_days(e)
    assert set(flagged["reason"]) == {"mismatch", "invalid"}


def test_gas_year_runs_october_to_september():
    assert list(le.gas_year(pd.to_datetime(["2025-09-30", "2025-10-01", "2026-03-01"]))) == ["2024/25", "2025/26", "2025/26"]


def test_target_summary_counts_the_days_each_target_keeps(monkeypatch):
    monkeypatch.setattr(le, "FEED_MATERIAL", 2.0)
    t = le.target_summary(le.energy_frame(raw_rows(se_total_day2=0.7), offtake_rows()))
    assert list(t.index) == sorted(LDZS) or set(t.index) == set(LDZS)
    assert t.loc["SE", ["days", "missing_feed", "target_a", "target_b", "repaired"]].tolist() == [3, 1, 2, 3, 1]
    assert t.loc["EA", ["target_a", "target_b", "repaired"]].tolist() == [3, 3, 0]
    assert "invalid" not in t.columns                                # flags that never occur are left out
