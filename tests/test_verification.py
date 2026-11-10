import numpy as np
import pandas as pd
import pytest

from ldz_demand.models import verification as v


def test_coverage_test_matches_the_hand_working():
    # 197 of 217 inside, as on 10 Nov 2026: naive z = (0.908 - 0.8) / sqrt(0.16 / 217)
    inside = np.r_[np.ones(197), np.zeros(20)].astype(bool)
    t = v.coverage_test(inside, np.arange(217))  # every pair its own cluster: cluster-robust ~ binomial at p-hat
    assert t["share"] == pytest.approx(197 / 217)
    assert t["z"] == pytest.approx((197 / 217 - 0.8) / np.sqrt(0.16 / 217))
    assert t["se_cluster"] == pytest.approx(np.sqrt(217 / 216 * (197 / 217) * (20 / 217) / 217), rel=1e-6)
    assert t["design_effect"] == pytest.approx(217 / 216, rel=1e-6)


def test_clustering_widens_the_standard_error_when_a_cluster_misses_together():
    # 10 days, each scored 5 times; two days missed by every run: the misses come in blocks
    inside = np.repeat([True] * 8 + [False] * 2, 5)
    days = np.repeat(np.arange(10), 5)
    t = v.coverage_test(inside, days)
    assert t["clusters"] == 10 and t["share"] == pytest.approx(0.8)
    assert t["design_effect"] == pytest.approx(5 * 10 / 9, rel=1e-6)  # the whole cluster size, small-sample adjusted


def test_pit_puts_each_actual_in_its_band_and_expects_the_band_widths():
    cols = {f"p{q:02d}": [float(q)] * 3 for q in v.PIT_PERCENTILES}
    scored = pd.DataFrame({**cols, "actual": [1.0, 60.0, 99.0]})
    p = v.pit(scored)
    assert p["expected"].sum() == pytest.approx(1)
    assert list(p.loc[p["days"] > 0, "band"]) == ["below P05", "P50–P75", "above P95"]


def test_ranks_count_members_below_era5_and_the_histogram_is_flat_for_a_calibrated_ensemble():
    rng = np.random.default_rng(1)
    days = pd.date_range("2026-01-01", periods=400)
    members = pd.DataFrame([(d, m, x) for d in days for m, x in zip(range(1, 51), rng.normal(size=50))],
                           columns=["gas_day", "member", "cwv"]).assign(ldz="NT", run_date=days[0], lead_days=0)
    era5 = pd.DataFrame({"ldz": "NT", "gas_day": days, "cwv": rng.normal(size=len(days))})
    r = v.ranks(members, era5)
    assert r["rank"].between(0, 50).all() and len(r) == len(days)
    h = v.rank_histogram(r)
    assert h["expected"].sum() == pytest.approx(1) and v.chi2_flat(h)["p"] > 0.01
    ss = v.spread_skill(r)
    assert ss["ratio"].iloc[0] == pytest.approx(1, abs=0.15)


def test_an_ensemble_that_is_too_narrow_piles_ranks_at_the_ends():
    rng = np.random.default_rng(2)
    days = pd.date_range("2026-01-01", periods=300)
    members = pd.DataFrame([(d, m, x) for d in days for m, x in zip(range(1, 51), 0.3 * rng.normal(size=50))],
                           columns=["gas_day", "member", "cwv"]).assign(ldz="NT", run_date=days[0], lead_days=0)
    era5 = pd.DataFrame({"ldz": "NT", "gas_day": days, "cwv": rng.normal(size=len(days))})
    h = v.rank_histogram(v.ranks(members, era5))
    assert h["observed"].iloc[[0, -1]].sum() > 3 * h["expected"].iloc[[0, -1]].sum()
    assert v.spread_skill(v.ranks(members, era5))["ratio"].iloc[0] < 0.5
