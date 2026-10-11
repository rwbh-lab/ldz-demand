import pandas as pd
import pytest

from ldz_demand.data.store.base import Dataset, conform

DS = Dataset(
    "test_daily",
    columns={"gas_day": "date", "ldz": "str", "value": "float"},
    keys=("gas_day", "ldz"),
)


def test_dataset_rejects_bad_schema():
    with pytest.raises(ValueError, match="unknown dtypes"):
        Dataset("x", columns={"gas_day": "date", "v": "decimal"}, keys=("gas_day",))
    with pytest.raises(ValueError, match="not in columns"):
        Dataset("x", columns={"gas_day": "date"}, keys=("ldz",))


def test_conform_selects_orders_and_coerces():
    df = pd.DataFrame({
        "value": ["1.5", "2"],
        "extra": [0, 0],
        "ldz": ["SE", "NW"],
        "gas_day": ["2026-01-01", "2026-01-01"],
    })
    out = conform(DS, df)

    assert list(out.columns) == ["gas_day", "ldz", "value"]
    assert pd.api.types.is_datetime64_any_dtype(out["gas_day"])
    assert out["value"].dtype == "float64"
    assert out["value"].tolist() == [1.5, 2.0]


def test_conform_rejects_missing_columns_null_and_duplicate_keys():
    with pytest.raises(ValueError, match="missing columns"):
        conform(DS, pd.DataFrame({"gas_day": ["2026-01-01"], "ldz": ["SE"]}))
    with pytest.raises(ValueError, match="null key"):
        conform(DS, pd.DataFrame({"gas_day": ["2026-01-01"], "ldz": [None], "value": [1.0]}))
    with pytest.raises(ValueError, match="duplicate keys"):
        conform(DS, pd.DataFrame({"gas_day": ["2026-01-01"] * 2, "ldz": ["SE"] * 2, "value": [1.0, 2.0]}))
