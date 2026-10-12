import pandas as pd
import pytest

from ldz_demand.charts import geography as g
from ldz_demand.charts import style
from ldz_demand.geo import boundaries, gas_use
from ldz_demand.geo.ldz_membership import read_table


@pytest.fixture(scope="module")
def las():
    style.use()
    return read_table("ldz_local_authority.csv")


def test_boundaries_and_gas_use_cover_every_authority(las):
    ids = {f["id"] for f in boundaries.load()["features"]}
    assert ids == set(las["lad23cd"])
    assert set(gas_use.load()["lad24cd"]) == set(las["lad24cd"])


def test_neighbouring_ldzs_never_share_a_colour(las):
    touches, _ = g._ldz_shapes(g._key(las))
    colours = g.ldz_colours(las)
    assert all(colours[a] != colours[b] for a in touches for b in touches[a])
    assert len(set(colours.values())) <= g.MAP_SLOTS


def test_map_embeds_boundaries_once(las):
    towns = read_table("ldz_towns.csv")
    for view in ("ldz", "confidence"):
        fig = g.ldz_map(las, towns, view=view)
        assert len(fig.to_json()) < 2_000_000  # one copy of the ~0.5 MB boundaries, not one per trace


def test_membership_check_shares_sum_to_100(las):
    check = g.membership_check(las, gas_use.load(), None)
    assert check["desnz_share"].sum() == pytest.approx(100)
    assert set(check["ldz"]) == set(las["main_ldz"])
