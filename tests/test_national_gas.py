"""National Gas: ingest (download + archive) and the ng_ldz_daily builder."""

from datetime import date, timedelta

import pandas as pd
import pytest

from ldz_demand.data.build.ng_ldz_daily import NGLdzDailyBuilder, latest_values, parse
from ldz_demand.data.datasets import NG_LDZ_DAILY
from ldz_demand.data.ingest.national_gas import (
    HISTORY_DAYS,
    ITEMS,
    LDZS,
    NationalGasError,
    NationalGasIngestor,
    archived_pulls,
    identify,
)
from ldz_demand.data.store import CsvCacheStore

HEADER = "Applicable At,Applicable For,Data Item,Value,Generated Time,Quality Indicator\n"

# Data Item text as the portal publishes it (taken from a real pull, LDZ substituted)
TEMPLATES = {
    "demand_total_d1": "Demand Actual, LDZ ({ldz}), D+1",
    "demand_total_d6": "Demand Actual, LDZ ({ldz}), D+6",
    "demand_dm_d1": "Demand, Actual DM, LDZ({ldz}), D+1",
    "demand_dm_d6": "Demand, Actual DM, LDZ({ldz}), D+6",
    "demand_ndm_d1": "Demand, Actual NDM, LDZ({ldz}), D+1",
    "demand_ndm_d6": "Demand, Actual NDM, LDZ({ldz}), D+6",
    "demand_uig_d1": "Demand, Actual UIG, LDZ({ldz}), D+1",
    "demand_uig_d6": "Demand, Actual UIG, LDZ({ldz}), D+6",
    "cv": "Calorific Value, LDZ({ldz})",
    "cwv_actual": "Composite Weather Variable, Actual, LDZ({ldz}), D+1",
}


def csv_line(item, ldz, gas_day="31/01/2026", value="18.77856", quality=""):
    return f'06/02/2026 11:38:00,{gas_day},"{TEMPLATES[item].format(ldz=ldz)}",{value},06/02/2026 12:00:00,{quality}\n'


# --- item registry ------------------------------------------------------------------------------

def test_every_item_and_ldz_is_identified():
    assert set(TEMPLATES) == set(ITEMS)
    for name in ITEMS:
        for ldz in LDZS:
            item, found_ldz = identify(TEMPLATES[name].format(ldz=ldz))
            assert (item.name, found_ldz) == (name, ldz)


def test_ids_are_complete_and_unique():
    ids = [item.ids[ldz] for item in ITEMS.values() for ldz in LDZS]
    assert len(ids) == len(set(ids)) == len(ITEMS) * len(LDZS)


# --- ingest: download + archive -----------------------------------------------------------------

class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


class FakeSession:
    """Returns one demand_total_d6 SE row per requested gas day; value = day of month."""

    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        start, end = date.fromisoformat(params["dateFrom"]), date.fromisoformat(params["dateTo"])
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        lines = [csv_line("demand_total_d6", "SE", gas_day=d.strftime("%d/%m/%Y"), value=str(d.day)) for d in days]
        return FakeResponse((HEADER + "".join(lines)).encode())


@pytest.fixture
def ingestor(tmp_path):
    return NationalGasIngestor(tmp_path / "raw", items=["demand_total_d6"], ldzs=["SE"], session=FakeSession())


def test_pull_chunks_by_year_and_archives_each_response(ingestor, tmp_path):
    files = ingestor.pull(date(2025, 12, 30), date(2026, 1, 2))

    calls = ingestor.session.calls
    assert [(c["dateFrom"], c["dateTo"]) for c in calls] == [("2025-12-30", "2025-12-31"), ("2026-01-01", "2026-01-02")]
    assert calls[0]["ids"] == "PUBOB646"
    assert ingestor.session.headers["User-Agent"].startswith("ldz-demand")
    assert [f.parent.name for f in files] == ["2025", "2026"]
    assert files[0].read_bytes().startswith(b"Applicable At")

    pulls = archived_pulls(tmp_path / "raw")
    assert [(p.start, p.end) for p in pulls] == [(date(2025, 12, 30), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 1, 2))]


def test_repeat_pull_never_overwrites(ingestor, tmp_path):
    ingestor.pull(date(2026, 1, 1), date(2026, 1, 2))
    ingestor.pull(date(2026, 1, 1), date(2026, 1, 2))
    assert len(list((tmp_path / "raw").rglob("*.csv"))) == 2


def test_refresh_full_history_then_from_archive(ingestor):
    today = date(2026, 10, 11)
    ingestor.refresh(today)
    assert ingestor.session.calls[0]["dateFrom"] == (today - timedelta(days=HISTORY_DAYS)).isoformat()
    assert ingestor.session.calls[-1]["dateTo"] == "2026-10-10"

    ingestor.session.calls.clear()
    ingestor.refresh(date(2026, 10, 20))
    assert [(c["dateFrom"], c["dateTo"]) for c in ingestor.session.calls] == [("2026-09-30", "2026-10-19")]


# --- build: archive -> ng_ldz_daily -------------------------------------------------------------

def test_parse_units_dates_and_missing_values():
    content = (HEADER
               + csv_line("demand_total_d6", "SE", value="18.77856")
               + csv_line("demand_dm_d6", "SE", value="23440679", quality="L")
               + csv_line("cv", "WM", value="")).encode()
    df = parse(content)

    se_total = df[(df["item"] == "demand_total_d6") & (df["ldz"] == "SE")].iloc[0]
    assert se_total["unit"] == "mcm"
    assert se_total["data_item_id"] == "PUBOB646"
    assert se_total["gas_day"] == pd.Timestamp("2026-01-31")
    assert se_total["applicable_at"] == pd.Timestamp("2026-02-06 11:38:00")
    assert pd.isna(se_total["quality"])
    assert df.loc[df["item"] == "demand_dm_d6", "unit"].item() == "kWh"
    assert df.loc[df["item"] == "demand_dm_d6", "quality"].item() == "L"
    assert pd.isna(df.loc[df["item"] == "cv", "value"].item())


def test_parse_handles_thousands_separators():
    content = (HEADER + csv_line("demand_dm_d6", "SE", value='"2,489,711"')).encode()
    assert parse(content)["value"].item() == 2489711


def test_parse_rejects_unknown_items_and_bad_columns():
    with pytest.raises(NationalGasError, match="Unrecognised data items"):
        parse((HEADER + '06/02/2026 11:38:00,31/01/2026,"Something Else, LDZ(SE)",1,06/02/2026 12:00:00,\n').encode())
    with pytest.raises(NationalGasError, match="Unexpected columns"):
        parse(b"a,b\n1,2\n")


def test_latest_values_prefers_newest_pull_with_a_value():
    row = {"gas_day": pd.Timestamp("2026-01-01"), "ldz": "SE", "item": "demand_total_d6"}
    df = pd.DataFrame([
        {**row, "value": 1.0, "_pulled": "20260101T000000Z"},
        {**row, "value": 2.0, "_pulled": "20260102T000000Z"},   # newer value wins over older
        {**row, "value": None, "_pulled": "20260103T000000Z"},  # newer blank does not erase it
    ])
    assert latest_values(df)["value"].tolist() == [2.0]


def test_build_from_archive_then_rebuild_is_idempotent(ingestor, tmp_path):
    ingestor.pull(date(2025, 12, 30), date(2026, 1, 2))
    store = CsvCacheStore(tmp_path / "cache")
    builder = NGLdzDailyBuilder(store, tmp_path / "raw")

    assert builder.build() == 4
    assert builder.build() == 4  # replace: same rows rewritten
    stored = store.read(NG_LDZ_DAILY)
    assert len(stored) == 4
    assert set(stored["unit"]) == {"mcm"}


def test_build_since_only_touches_recent_rows(ingestor, tmp_path):
    ingestor.pull(date(2025, 12, 30), date(2026, 1, 2))
    store = CsvCacheStore(tmp_path / "cache")
    builder = NGLdzDailyBuilder(store, tmp_path / "raw")

    assert builder.build(since=date(2026, 1, 2)) == 1
    assert store.read(NG_LDZ_DAILY)["gas_day"].tolist() == [pd.Timestamp("2026-01-02")]


def test_build_with_empty_archive_writes_nothing(tmp_path):
    assert NGLdzDailyBuilder(CsvCacheStore(tmp_path / "cache"), tmp_path / "raw").build() == 0


# --- offtakes series ----------------------------------------------------------------------------

def offtake_line(site, code, gas_day="31/01/2026", value='"2,489,711"'):
    return f'01/02/2026 12:01:01,{gas_day},"NTS Energy Offtaken, {site}, {code}, LDZ Offtake",{value},01/02/2026 12:01:01,L\n'


def test_offtake_registry_and_identify():
    from ldz_demand.data.ingest.national_gas import OFFTAKES, identify_offtake

    ids = [i for sites in OFFTAKES.values() for i in sites.values()]
    assert len(ids) == len(set(ids)) == 122
    assert set(OFFTAKES) == set(LDZS)
    assert identify_offtake("NTS Energy Offtaken, Shorne, SE, LDZ Offtake") == ("SE", "Shorne", "PUBOBJ943")
    # Peters Green has a second item published under "SM", which also feeds North Thames
    assert identify_offtake("NTS Energy Offtaken, PetersGrn, SM, LDZ Offtake") == ("NT", "PetersGrnSM", "PUBOBJ929")
    assert identify_offtake("NTS Energy Offtaken, Nowhere, SE, LDZ Offtake") is None


def test_offtake_pull_archives_separately_and_builds(tmp_path):
    from ldz_demand.data.build.ng_offtake_daily import NGOfftakeDailyBuilder
    from ldz_demand.data.datasets import NG_OFFTAKE_DAILY

    class OfftakeSession(FakeSession):
        def get(self, url, params, timeout):
            self.calls.append(params)
            body = HEADER + offtake_line("Shorne", "SE") + offtake_line("PetersGrn", "SM", value="5")
            return FakeResponse(body.encode())

    ing = NationalGasIngestor(tmp_path / "raw", series="offtakes", ldzs=["SE"], session=OfftakeSession())
    files = ing.pull(date(2026, 1, 31), date(2026, 1, 31))
    assert files[0].parent.parent.name == "offtakes" and files[0].name.startswith("ng_offtakes_")
    assert ing.session.calls[0]["ids"].split(",") == ["PUBOBJ887", "PUBOBJ2028", "PUBOBJ943", "PUBOBJ950", "PUBOBJ963"]
    assert archived_pulls(tmp_path / "raw", "ldz") == []  # series don't mix
    assert len(archived_pulls(tmp_path / "raw", "offtakes")) == 1

    store = CsvCacheStore(tmp_path / "cache")
    assert NGOfftakeDailyBuilder(store, tmp_path / "raw").build() == 2
    df = store.read(NG_OFFTAKE_DAILY).set_index("site")
    assert df.loc["Shorne", "value"] == 2489711
    assert df.loc["PetersGrnSM", "ldz"] == "NT"
    assert set(df["unit"]) == {"kWh"}
