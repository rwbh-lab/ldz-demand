import pytest

from ldz_demand.charts import geography as g
from ldz_demand.charts import style
from ldz_demand.geo import postcode_sample as ps
from ldz_demand.geo.ldz_membership import read_table


def test_resolvable_needs_a_checker_that_tells_the_candidates_apart():
    assert ps.resolvable(["SW", "SO"])            # WWU vs SGN
    assert ps.resolvable(["NT", "SO"])            # Cadent inferred when SGN says no
    assert ps.resolvable(["EM", "SO", "WM", "EA"])  # several Cadent candidates share the "other" results
    assert not ps.resolvable(["EA", "NT"])        # both Cadent: no checker
    assert not ps.resolvable(["SO", "SE"])        # both SGN
    assert not ps.resolvable(["SO"])


def test_classify_uses_the_operator_answers():
    assert ps.classify(["SW", "SO"], {"SGN": True, "WWU": False}) == "SO"
    assert ps.classify(["SW", "SO"], {"SGN": False, "WWU": True}) == "SW"
    assert ps.classify(["SW", "SO"], {"SGN": False, "WWU": False}) is None  # off network or not in either list
    assert ps.classify(["SW", "SO"], {"SGN": True, "WWU": True}) is None
    assert ps.classify(["NT", "SO"], {"SGN": False}) == "other"
    assert ps.checkers_needed(["NT", "SO"]) == ["SGN"]


def test_shares_spread_other_over_the_remaining_candidates_by_vote():
    votes = {"EM": 3.0, "SO": 1.0, "WM": 1.0}
    results = ["SO"] * 5 + ["other"] * 15 + [None] * 3
    s = ps.shares(ps.candidates(votes), votes, results)
    assert s == pytest.approx({"SO": 0.25, "EM": 0.75 * 0.75, "WM": 0.75 * 0.25})
    assert ps.shares(["SW", "SO"], {"SW": 1, "SO": 1}, ["SO"] * (ps.MIN_RESOLVED - 1)) is None  # too few resolved


def test_sampled_method_allocates_every_authority_in_full():
    las = read_table("ldz_local_authority.csv")
    shares = ps.authority_shares()
    assert set(shares.index) == set(las["lad23cd"])
    assert (shares.sum(axis=1).round(6) == 1).all()


def test_committed_sample_is_consistent():
    sample = ps.load()
    if sample.empty:
        pytest.skip("postcode sample not built")
    assert sample.groupby("lad23cd").size().max() <= ps.SAMPLE_SIZE
    resolved = sample.dropna(subset=["result"])
    for r in resolved.itertuples():
        assert r.result == "other" or r.result in r.candidates.split("/")
    assert resolved["lat"].between(49.8, 61).all() and resolved["lon"].between(-8.7, 2).all()


def test_sampled_map_stays_small():
    style.use()
    fig = g.ldz_map(read_table("ldz_local_authority.csv"), method="sampled")
    assert len(fig.to_json()) < 2_000_000
