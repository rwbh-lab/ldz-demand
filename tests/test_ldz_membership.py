import pandas as pd

from ldz_demand.geo import ldz_membership as m

PAGE = """
<p>Towns</p><figure class="wp-block-table"><table><tbody>
<tr><td>Brighton</td></tr><tr><td>Bishop&#8217;s Stortford</td></tr><tr><td>Brighton</td></tr>
</tbody></table></figure>
<p>Counties</p><figure class="wp-block-table"><table><tbody><tr><td>Kent&nbsp;</td></tr></tbody></table></figure>
"""


def test_parse_broker_page_dedupes_and_unescapes():
    parsed = m.parse_broker_page(PAGE)
    assert parsed["towns"] == ["Brighton", "Bishop’s Stortford"]
    assert parsed["counties"] == ["Kent"]


def test_norm_handles_apostrophes_saint_and_punctuation():
    assert m.norm("Bishop’s Stortford") == m.norm("Bishop's Stortford") == "bishops stortford"
    assert m.norm("Saint Leonards-on-sea") == "st leonards on sea"


def ipn_row(name, lad, ladnm, lat, lon, descnm="BUA", county=""):
    return {"place23nm": name, "lad23cd": lad, "lad23nm": ladnm, "lat": lat, "lon": lon, "descnm": descnm,
            "ctyhistnm": county, "cty61nm": "", "cty91nm": "", "ctyltnm": "", "cty23nm": "", "ctry23nm": "England"}


def test_match_uses_counties_then_footprint():
    ipn = pd.DataFrame([
        ipn_row("Ashford", "E1", "Ashford", 51.15, 0.87, county="Kent"),
        ipn_row("Ashford", "E2", "Spelthorne", 51.43, -0.46, county="Middlesex"),
        ipn_row("Staines", "E2", "Spelthorne", 51.43, -0.51, county="Middlesex"),
        ipn_row("Newtown", "E3", "Far Away", 57.0, -4.0),
        ipn_row("Newtown", "E4", "Nearby", 51.45, -0.40),
    ])
    ipn["key"] = ipn["place23nm"].map(m.norm)
    lists = {"NT": {"towns": ["Ashford", "Staines", "Newtown"], "counties": ["Middlesex"]}}
    towns = m.match_towns(lists, ipn).set_index("town")
    assert towns.loc["Ashford", "lad23nm"] == "Spelthorne"      # county decides
    assert towns.loc["Newtown", "lad23nm"] == "Nearby"          # nearest to the LDZ's other towns
    assert towns.loc["Newtown", "method"] == "footprint"


def test_outliers_flag_towns_far_from_their_ldz_but_next_to_another():
    centres = {("EM", "Derby"): (52.92, -1.48), ("EM", "Nottingham"): (52.95, -1.15),
               ("EM", "Basingstoke"): (51.27, -1.09), ("SO", "Andover"): (51.21, -1.48),
               ("SO", "Winchester"): (51.06, -1.31)}
    assert m._outliers(centres) == {("EM", "Basingstoke")}


def test_assign_authorities_unanimous_split_and_nearest():
    towns = pd.DataFrame([
        {"ldz": "NT", "town": "A", "lat": 51.5, "lon": -0.1, "lad23cd": "L1", "method": "county"},
        {"ldz": "NT", "town": "B", "lat": 51.5, "lon": -0.2, "lad23cd": "L2", "method": "county"},
        {"ldz": "SE", "town": "C", "lat": 51.3, "lon": 0.1, "lad23cd": "L2", "method": "county"},
        {"ldz": "SE", "town": "D", "lat": 51.0, "lon": 0.5, "lad23cd": "L9", "method": "outlier"},
    ])
    lads = pd.DataFrame([
        {"lad23cd": "L1", "lad24cd": "L1", "lad23nm": "One", "lat": 51.5, "lon": -0.1, "country": "England"},
        {"lad23cd": "L2", "lad24cd": "L2", "lad23nm": "Two", "lat": 51.4, "lon": -0.05, "country": "England"},
        {"lad23cd": "L3", "lad24cd": "L3", "lad23nm": "Three", "lat": 51.31, "lon": 0.11, "country": "England"},
    ])
    out = m.assign_authorities(towns, lads).set_index("lad23cd")
    assert out.loc["L1", ["ldz", "method"]].tolist() == ["NT", "unanimous"]
    assert out.loc["L2", ["ldz", "main_ldz"]].tolist() == ["split", "NT"]
    assert out.loc["L3", "ldz"] == "SE" and out.loc["L3", "method"].startswith("nearest_town")

    overrides = pd.DataFrame([{"lad23cd": "L2", "ldz": "SE", "reason": "checked"}])
    assert m.assign_authorities(towns, lads, overrides).set_index("lad23cd").loc["L2", "ldz"] == "SE"

    # "split" forces a split (keeping the votes) where one LDZ's share would make the authority single
    forced = pd.DataFrame([{"lad23cd": "L1", "ldz": "split", "reason": "postcodes in two LDZs"}])
    l1 = m.assign_authorities(towns, lads, forced).set_index("lad23cd").loc["L1"]
    assert l1[["ldz", "main_ldz", "method", "review"]].tolist() == ["split", "NT", "split", "postcodes in two LDZs"]


def test_correct_towns_moves_listed_towns_and_keeps_the_source_ldz():
    towns = pd.DataFrame([
        {"ldz": "NE", "town": "Sheffield", "method": "county"},
        {"ldz": "EM", "town": "Sheffield", "method": "county"},
        {"ldz": "NE", "town": "Leeds", "method": "county"},
    ])
    out = m.correct_towns(towns, {("NE", "Sheffield"): "EM"})
    assert len(out) == 2  # Sheffield now listed once, under EM
    assert out.set_index("town").loc["Leeds", ["ldz", "listed_ldz"]].tolist() == ["NE", "NE"]
    assert set(out["ldz"]) == {"EM", "NE"}


def test_committed_tables_cover_all_ldzs():
    las = m.read_table("ldz_local_authority.csv")
    assert len(las) == 350
    assert set(las["main_ldz"]) == set(m.LDZS)
    towns = m.read_table("ldz_towns.csv")
    assert towns["method"].str.replace("+corrected", "").isin(
        ["county", "footprint", "county+alias", "footprint+alias", "outlier", "outlier+alias",
         "ambiguous", "not_in_ipn", "ambiguous+alias", "not_in_ipn+alias"]).all()
    # every town correction found its town, and the corrected towns carry their source LDZ
    corrections = m.load_town_corrections()
    fixed = towns[towns["method"].str.contains("corrected")]
    assert set(zip(fixed["listed_ldz"], fixed["town"])) == set(corrections)
    assert (fixed["ldz"] != fixed["listed_ldz"]).all()
