from datetime import date, timedelta

import pandas as pd
import pytest

from ldz_demand.data.datasets import NG_LDZ_DAILY
from ldz_demand.data.ingest.national_gas import (
    HISTORY_DAYS,
    ITEMS,
    LDZS,
    NationalGasError,
    NationalGasIngestor,
    _identify,
    parse,
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


def test_every_item_and_ldz_is_identified():
    assert set(TEMPLATES) == set(ITEMS)
    for name in ITEMS:
        for ldz in LDZS:
            item, found_ldz = _identify(TEMPLATES[name].format(ldz=ldz))
            assert (item.name, found_ldz) == (name, ldz)


def test_ids_are_complete_and_unique():
    ids = [item.ids[ldz] for item in ITEMS.values() for ldz in LDZS]
    assert len(ids) == len(set(ids)) == len(ITEMS) * len(LDZS)


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


def test_parse_rejects_unknown_items_and_bad_columns():
    with pytest.raises(NationalGasError, match="Unrecognised data items"):
        parse((HEADER + '06/02/2026 11:38:00,31/01/2026,"Something Else, LDZ(SE)",1,06/02/2026 12:00:00,\n').encode())
    with pytest.raises(NationalGasError, match="Unexpected columns"):
        parse(b"a,b\n1,2\n")


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


class FakeSession:
    """Returns one demand_total_d6 SE row per requested gas day."""

    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        start, end = date.fromisoformat(params["dateFrom"]), date.fromisoformat(params["dateTo"])
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        lines = [csv_line("demand_total_d6", "SE", gas_day=d.strftime("%d/%m/%Y"), value=str(i)) for i, d in enumerate(days)]
        return FakeResponse((HEADER + "".join(lines)).encode())


@pytest.fixture
def ingestor(tmp_path):
    return NationalGasIngestor(
        CsvCacheStore(tmp_path / "cache"), tmp_path / "raw",
        items=["demand_total_d6"], ldzs=["SE"], session=FakeSession(),
    )


def test_pull_chunks_by_year_archives_raw_and_writes_store(ingestor, tmp_path):
    written = ingestor.pull(date(2025, 12, 30), date(2026, 1, 2))

    assert written == 4
    calls = ingestor.session.calls
    assert [(c["dateFrom"], c["dateTo"]) for c in calls] == [("2025-12-30", "2025-12-31"), ("2026-01-01", "2026-01-02")]
    assert calls[0]["ids"] == "PUBOB646"
    assert ingestor.session.headers["User-Agent"].startswith("ldz-demand")

    archived = sorted((tmp_path / "raw" / "national_gas").rglob("*.csv"))
    assert [p.parent.name for p in archived] == ["2025", "2026"]
    assert archived[0].read_bytes().startswith(b"Applicable At")

    stored = ingestor.store.read(NG_LDZ_DAILY)
    assert len(stored) == 4
    assert set(stored["unit"]) == {"mcm"}


def test_repeat_pull_archives_again_and_replaces_rows(ingestor, tmp_path):
    ingestor.pull(date(2026, 1, 1), date(2026, 1, 2))
    ingestor.pull(date(2026, 1, 1), date(2026, 1, 2))

    assert len(list((tmp_path / "raw").rglob("*.csv"))) == 2
    assert len(ingestor.store.read(NG_LDZ_DAILY)) == 2


def test_refresh_full_history_then_incremental(ingestor):
    today = date(2026, 10, 11)
    ingestor.refresh(today)
    assert ingestor.session.calls[0]["dateFrom"] == (today - timedelta(days=HISTORY_DAYS)).isoformat()
    assert ingestor.session.calls[-1]["dateTo"] == "2026-10-10"

    ingestor.session.calls.clear()
    ingestor.refresh(date(2026, 10, 20))
    assert [(c["dateFrom"], c["dateTo"]) for c in ingestor.session.calls] == [("2026-09-30", "2026-10-19")]
