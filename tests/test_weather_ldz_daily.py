from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ldz_demand.data.build.weather_ldz_daily import WeatherLdzDailyBuilder, ldz_weather
from ldz_demand.data.datasets import WEATHER_LDZ_DAILY
from ldz_demand.data.store import CsvCacheStore
from ldz_demand.geo import grid_weights as gw

LAT, LON = np.array([52.0, 51.75]), np.array([-1.0, -0.75])


def test_committed_weights_sum_to_one_for_every_variant_and_ldz():
    w = gw.load()
    sums = w.groupby(["membership", "weighting", "variable", "ldz"])["weight"].sum()
    assert np.allclose(sums, 1, atol=1e-5)
    assert len(sums) == (len(gw.MEMBERSHIPS) * len(gw.WEIGHTINGS) + 1) * 2 * 13
    lats, lons = gw.era5_grid()
    assert w["lat"].isin(lats).all() and w["lon"].isin(lons).all()


def test_bilinear_station_weights():
    lats, lons = [52.0, 51.75], [-1.0, -0.75]
    assert gw.bilinear(52.0, -1.0, lats, lons) == [(52.0, -1.0, 1.0)]
    corners = gw.bilinear(51.875, -0.875, lats, lons)
    assert len(corners) == 4 and all(w == pytest.approx(0.25) for *_, w in corners)
    with pytest.raises(ValueError):
        gw.bilinear(60.0, -1.0, lats, lons)


def test_station_reference_uses_its_own_wind_station_for_wm():
    s = gw.station_weights()
    wm = s[s["ldz"] == "WM"]
    centre = wm.assign(lon_w=wm["lon"] * wm["weight"]).groupby("variable")["lon_w"].sum()
    assert centre["ws10"] > centre["t2m"]  # Coleshill is east of Winterbourne


def weights(rows):
    return pd.DataFrame([dict(zip(["membership", "weighting", "variable", "ldz", "lat", "lon", "weight"], r)) for r in rows])


def daily_field(t2m, ws10=5.0, days=2):
    gas_day = pd.date_range("2026-01-01", periods=days)
    shape = (days, len(LAT), len(LON))
    return xr.Dataset(
        {"t2m": (("gas_day", "latitude", "longitude"), np.broadcast_to(t2m, shape).astype(float)),
         "ws10": (("gas_day", "latitude", "longitude"), np.full(shape, ws10))},
        coords={"gas_day": gas_day, "latitude": LAT, "longitude": LON})


def test_ldz_weather_is_the_weighted_mean_of_the_cells():
    w = weights([("hybrid", "gas", v, "NT", la, lo, 0.25) for v in ("t2m", "ws10") for la in LAT for lo in LON]
                + [("station", "point", v, "NT", 52.0, -1.0, 1.0) for v in ("t2m", "ws10")])
    gradient = np.array([[10.0, 12.0], [14.0, 16.0]])  # by latitude row, longitude column
    out = ldz_weather(daily_field(gradient), w).set_index(["membership", "variable", "gas_day"])["value"]
    assert out[("hybrid", "t2m", pd.Timestamp("2026-01-01"))] == pytest.approx(13.0)
    assert out[("station", "t2m", pd.Timestamp("2026-01-01"))] == pytest.approx(10.0)
    assert out[("hybrid", "ws10", pd.Timestamp("2026-01-02"))] == pytest.approx(5.0)


def test_weights_outside_the_grid_are_refused():
    w = weights([("hybrid", "gas", "t2m", "NT", 55.0, -1.0, 1.0), ("hybrid", "gas", "ws10", "NT", 55.0, -1.0, 1.0)])
    with pytest.raises(ValueError, match="outside the ERA5 grid"):
        ldz_weather(daily_field(10.0), w)


def era5_month(raw, month: str, name: str, kelvin: float):
    """A month of hourly ERA5 shaped like a CDS download, uniform in space."""
    times = pd.date_range(f"{month}-01", pd.Period(month, freq="M").end_time.floor("h"), freq="h")
    shape = (len(times), len(LAT), len(LON))
    ds = xr.Dataset(
        {"t2m": (("valid_time", "latitude", "longitude"), np.full(shape, kelvin)),
         "u10": (("valid_time", "latitude", "longitude"), np.full(shape, 3.0)),
         "v10": (("valid_time", "latitude", "longitude"), np.full(shape, -4.0))},
        coords={"valid_time": times, "latitude": LAT, "longitude": LON})
    path = raw / "era5" / month[:4] / name
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path)


def test_builder_writes_complete_gas_days_with_their_source(tmp_path):
    raw = tmp_path / "raw"
    era5_month(raw, "2026-01", "era5_gb_2026-01.nc", 278.15)
    era5_month(raw, "2026-02", "era5t_gb_2026-02_pulled_20260310T000000Z.nc", 283.15)
    w = weights([("sampled", "area", v, "SO", la, lo, 0.25) for v in ("t2m", "ws10") for la in LAT for lo in LON])
    store = CsvCacheStore(tmp_path / "cache")
    WeatherLdzDailyBuilder(store, raw, weights=w).build()

    out = store.read(WEATHER_LDZ_DAILY)
    t = out[out["variable"] == "t2m"].set_index("gas_day")
    # January: 31 gas days (31 Jan needs 1 Feb's early hours); February: the last gas day is incomplete
    assert len(t) == 31 + 27
    assert t.loc[pd.Timestamp("2026-01-15"), "value"] == pytest.approx(5.0)
    assert t.loc[pd.Timestamp("2026-01-15"), "source"] == "era5"
    assert t.loc[pd.Timestamp("2026-01-31"), "source"] == "era5t"  # its last hours are preliminary
    assert t.loc[pd.Timestamp("2026-02-10"), "value"] == pytest.approx(10.0)
    ws = out[out["variable"] == "ws10"]
    assert np.allclose(ws["value"], 5.0)  # hourly speed from u = 3, v = -4, then averaged

    # rebuilding replaces rows rather than adding them
    WeatherLdzDailyBuilder(store, raw, weights=w).build(since="2026-02")
    assert len(store.read(WEATHER_LDZ_DAILY)) == len(out)


def test_comparison_separates_steady_offsets_from_day_to_day_differences():
    from ldz_demand.charts import weather_ldz as wx

    days = pd.date_range("2026-01-01", periods=4)
    ref = np.array([1.0, 2.0, 3.0, 4.0])
    rows = []
    for (m, w), values in {("sampled", "gas"): ref, ("hybrid", "area"): ref + 0.5,
                           ("station", "point"): ref + np.array([0.0, 1.0, 0.0, 1.0])}.items():
        rows += [{"gas_day": d, "ldz": "NT", "membership": m, "weighting": w, "variable": "t2m", "value": v}
                 for d, v in zip(days, values)]
    stats = wx.comparison(pd.DataFrame(rows), "t2m").set_index("membership")
    assert stats.loc["hybrid", "mean_diff"] == pytest.approx(0.5) and stats.loc["hybrid", "sd_diff"] == pytest.approx(0)
    assert stats.loc["station", "sd_diff"] == pytest.approx(np.std([0, 1, 0, 1], ddof=1))
    assert stats.loc["station", "max_abs_diff"] == pytest.approx(1.0)


def test_prepare_gives_the_same_comparison_as_the_long_table():
    from ldz_demand.charts import weather_ldz as wx

    days = pd.date_range("2026-01-01", periods=5)
    rows = [{"gas_day": d, "ldz": z, "membership": m, "weighting": w, "variable": v, "value": i * 0.1 + hash((z, m, v)) % 7}
            for i, d in enumerate(days) for z in ("NT", "SO") for m, w in (("sampled", "gas"), ("station", "point"))
            for v in ("t2m", "ws10")]
    long = pd.DataFrame(rows)
    wide = wx.prepare(long)
    assert set(wide) == {"t2m", "ws10"} and wide["t2m"].shape == (5, 4)
    pd.testing.assert_frame_equal(wx.comparison(wide, "ws10"), wx.comparison(long, "ws10"))


def test_page_menu_links_every_page_and_marks_the_current_one():
    from pathlib import Path

    from ldz_demand.charts import pages

    dashboard = Path(__file__).parent.parent / "dashboard"
    assert set(pages.PAGES) | {pages.INDEX} == {p.name for p in dashboard.glob("*.py")}
    lines = pages.contents_markdown("ldz_weather.py").split("  \n")
    assert lines == ["Project: [Project map](/project-map)",
                     "Data: [National Gas data](/ng-ldz-daily) | [ERA5 weather](/era5-weather)",
                     "Pre-CWV models: [LDZ geography](/ldz-geography) | **LDZ weather** | [Ensemble LDZ weather](/ensemble-forecasts)",
                     "CWV model: [Demand model](/demand-model)",
                     "Outputs: [Results](/results)"]
    assert "(/)" in pages.nav("ldz_weather.py").text or 'href="/"' in pages.nav("ldz_weather.py").text


def test_dashboard_server_mounts_the_overview_at_root_and_every_page(monkeypatch):
    import marimo

    from ldz_demand import dashboard
    from ldz_demand.charts import pages

    mounted = {}

    class Builder:
        def with_app(self, path, root):
            mounted[path] = root
            return self

        def build(self):
            return "app"

    monkeypatch.setattr(marimo, "create_asgi_app", lambda: Builder())
    assert dashboard.build_app() == "app"
    assert mounted["/"].endswith("dashboard/index.py")
    assert {p.path for p in pages.PAGES.values()} | {"/"} == set(mounted)
    assert all(Path(root).exists() for root in mounted.values())
