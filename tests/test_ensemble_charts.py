import numpy as np
import pandas as pd
import pytest

from ldz_demand.charts import ensemble as ens
from ldz_demand.charts import style

RUN = pd.Timestamp("2026-10-13")


def rows(values_by_ldz: dict[str, np.ndarray], variable="t2m"):
    """ens_ldz_daily-shaped rows: values[member, lead] per LDZ, for the reference variant."""
    out = []
    for ldz, v in values_by_ldz.items():
        for m in range(v.shape[0]):
            for lead in range(v.shape[1]):
                out.append({"run_date": RUN, "member": m + 1, "lead_days": lead, "ldz": ldz, "membership": "sampled",
                            "weighting": "gas", "variable": variable, "value": v[m, lead]})
    return pd.DataFrame(out)


def test_gb_is_the_gas_weighted_average_of_the_ldzs():
    da = ens.cube(rows({"NT": np.full((5, 3), 10.0), "SC": np.full((5, 3), 4.0)}))
    gb = ens.with_gb(da, pd.Series({"NT": 0.75, "SC": 0.25}))
    assert float(gb.sel(ldz="GB").mean()) == pytest.approx(8.5)
    assert list(gb["ldz"].values)[0] == "GB"


def test_asymmetry_symmetric_and_cold_tailed_spreads():
    q = np.linspace(0.01, 0.99, 50)
    from scipy.stats import norm

    symmetric = norm.ppf(q)[:, None].repeat(2, axis=1)
    cold_tail = -np.exp(norm.ppf(q) * 0.6)[:, None].repeat(2, axis=1)   # long tail towards low values
    da = ens.cube(rows({"NT": symmetric, "SC": cold_tail}))
    sym = ens.asymmetry(da.sel(variant="sampled/gas", variable="t2m", ldz="NT"))
    assert np.allclose(sym["lower"], sym["upper"], rtol=0.02) and np.allclose(sym["kelly"], 0, atol=0.02)
    assert np.allclose(sym["lower_sd"], sym["upper_sd"], rtol=0.02)
    cold = ens.asymmetry(da.sel(variant="sampled/gas", variable="t2m", ldz="SC"))
    assert (cold["lower"] > cold["upper"]).all() and (cold["kelly"] < 0).all()
    assert (cold["lower_sd"] > cold["upper_sd"]).all()                  # still lopsided once scaled


def test_charts_build_for_both_scales_and_options():
    style.use()
    rng = np.random.default_rng(0)
    values = rng.normal(10, 1, (50, 15)) * np.linspace(0.2, 2.5, 15)
    da = ens.with_gb(ens.cube(pd.concat([rows({"NT": values}), rows({"NT": values + 0.5}).assign(membership="station",
                                                                                                    weighting="point")])),
                     pd.Series({"NT": 1.0}))
    for fig in (ens.fan_chart(da, RUN, "NT", "t2m", show_members=True, compare=("station", "point")),
                ens.asymmetry_chart(da, RUN, "NT", "t2m", scale="sd"),
                ens.asymmetry_chart(da, RUN, "NT", "t2m", scale="units"),
                ens.members_strip(da, RUN, "NT", "t2m", 9),
                ens.spread_heatmap(da, RUN, "t2m", "iqr"),
                ens.spread_heatmap(da, RUN, "t2m", "kelly")):
        assert fig.data and len(fig.layout.title.text) < 80
    fan = ens.fan_chart(da, RUN, "NT", "t2m", show_members=True)
    assert sum(1 for tr in fan.data if tr.showlegend is False and tr.hoverinfo == "skip") >= 50  # the members


def test_station_gap_note_puts_the_run_in_context():
    gap = pd.Series([0.9, 0.8, 0.85], index=[0, 1, 2])
    days = pd.date_range("2025-10-01", periods=40)
    history = pd.DataFrame(
        [{"gas_day": d, "ldz": "WS", "membership": m, "weighting": w, "variable": "t2m", "value": v}
         for d in days for m, w, v in (("station", "point", 10.8), ("sampled", "gas", 10.0))])
    from ldz_demand.charts.weather_ldz import station_offsets

    offsets = station_offsets(history, "t2m")
    usual = ens.station_gap_note(gap, offsets, "2026-10-13", "WS", "t2m")
    assert "+0.85 °C" in usual and "+0.80 °C" in usual and "where the station is" in usual
    odd = ens.station_gap_note(gap + 1.0, offsets, "2026-10-13", "WS", "t2m")
    assert "larger than usual" in odd


def test_mean_map_has_a_frame_per_full_lead_day():
    style.use()
    from ldz_demand.data.ingest.national_gas import LDZS

    rng = np.random.default_rng(0)
    da = ens.cube(rows({ldz: rng.normal(10, 1, (5, 15)) for ldz in LDZS}))
    fig = ens.mean_map(da, RUN)
    assert len(fig.frames) == 14 and len(fig.layout.sliders[0].steps) == 14   # lead days 0–13 (14 is partial)
    assert fig.layout.sliders[0].steps[0].label == "Tue 13"
    z = fig.data[0].z
    assert np.isfinite(np.asarray(z, dtype=float)).all()                       # every authority coloured
