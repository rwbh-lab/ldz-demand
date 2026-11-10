"""
Error analysis of the live forecasts, for the Error analysis page.

- Coverage: how often closed-out demand (Q_D+6) lands inside P10–P90, with a test against the 80% it should
  be. Each gas day is scored by up to 14 runs against the same actual, so the scored pairs are not
  independent: the test clusters them by gas day (a cluster-robust standard error), and lead day 0 alone
  (one forecast per gas day) is the clean check.
- Where demand lands among the stored percentiles (a PIT histogram): the tails as well as the middle.
- Where ERA5's weather lands among the 50 members' (a rank histogram), with the members' spread against the
  error of their mean: the weather forecast on its own, without the demand model or its error.

Member weather is run through the final model's CWV per run and cached (one CSV per run under the cache
directory): a past run's members don't change, so only new runs are computed.

    python -m ldz_demand.models.verification     # build the member CWV cache, print the coverage test
"""

import argparse
import logging
import sys
from math import sqrt

import numpy as np
import pandas as pd
from scipy import stats

from ldz_demand.data.ingest.national_gas import LDZS
from ldz_demand.models import demand
from ldz_demand.models import forecast as fc

logger = logging.getLogger(__name__)

TARGET = 0.8                                   # P10–P90 should hold 80% of days
LEAD_BANDS = ((0, 3), (4, 8), (9, 13))
PIT_PERCENTILES = (5, 10, 25, 50, 75, 90, 95)  # the stored percentiles (forecast.PERCENTILES)
MEMBERS = 50
CACHE_DIR = "member_cwv"                       # under the storage cache_dir


# ---------------------------------------------------------------- coverage

def coverage_test(inside, clusters, target: float = TARGET) -> dict:
    """
    The share of True in inside, tested against target two ways:
    - naive: the binomial standard error under H0, sqrt(p0 (1 - p0) / n), and the exact binomial p-value;
      right only if every pair is independent.
    - cluster-robust: pairs grouped by clusters (e.g. gas day), SE = sqrt(G/(G-1) · Σ_g (k_g - p̂ n_g)²) / n,
      tested with t on G - 1 degrees of freedom; allows for pairs that share an actual.
    Also the design effect (the cluster-robust variance over the binomial one at p̂): n / design effect is
    roughly how many independent days the pairs are worth.
    """
    x = pd.Series(inside).astype(float).to_numpy()
    n, k = len(x), int(x.sum())
    p = k / n
    se0 = sqrt(target * (1 - target) / n)
    g = pd.DataFrame({"x": x, "c": pd.Series(clusters).to_numpy()}).groupby("c")["x"].agg(["sum", "size"])
    n_clusters = len(g)
    r = g["sum"] - p * g["size"]
    se = sqrt(n_clusters / (n_clusters - 1) * float((r ** 2).sum())) / n if n_clusters > 1 else np.nan
    dof = n_clusters - 1
    t = (p - target) / se if se and se > 0 else np.nan
    tq = stats.t.ppf(0.975, dof) if dof > 0 else np.nan
    binomial_var = p * (1 - p) / n
    return dict(
        n=n, inside=k, share=p, target=target,
        se_naive=se0, z=(p - target) / se0, p_naive=stats.binomtest(k, n, target).pvalue,
        clusters=n_clusters, se_cluster=se, t=t, dof=dof,
        p_cluster=2 * stats.t.sf(abs(t), dof) if np.isfinite(t) else np.nan,
        lo=p - tq * se, hi=p + tq * se,
        design_effect=se ** 2 / binomial_var if binomial_var > 0 and np.isfinite(se) else np.nan,
    )


def exact_test(inside, target: float = TARGET) -> dict:
    """The exact binomial test for independent days: share, two-sided p-value, Clopper–Pearson 95% interval."""
    x = pd.Series(inside).astype(bool)
    res = stats.binomtest(int(x.sum()), len(x), target)
    ci = res.proportion_ci()
    return dict(n=len(x), inside=int(x.sum()), share=x.mean(), p=res.pvalue, lo=ci.low, hi=ci.high)


def coverage_by_lead(scored: pd.DataFrame) -> pd.DataFrame:
    """Per lead day: pairs scored, the share inside the blend's and the weather-only P10–P90, with exact 95%
    intervals (one forecast per gas day at a given lead, so the days are close to independent)."""
    rows = []
    for lead, g in scored.groupby("lead_days"):
        row = {"lead_days": int(lead), "n": len(g)}
        for name, col in (("blend", "in 10–90%"), ("weather", "in weather-only 10–90%")):
            e = exact_test(g[col])
            row.update({name: e["share"], f"{name}_lo": e["lo"], f"{name}_hi": e["hi"], f"{name}_inside": e["inside"]})
        rows.append(row)
    return pd.DataFrame(rows)


def coverage_by_band(scored: pd.DataFrame, bands=LEAD_BANDS) -> pd.DataFrame:
    """Per band of lead days: pairs, inside the blend's and the weather-only P10–P90."""
    rows = []
    for lo, hi in bands:
        g = scored[scored["lead_days"].between(lo, hi)]
        rows.append({"lead days": f"{lo}–{hi}", "pairs": len(g), "gas days": g["gas_day"].nunique(),
                     "blend": g["in 10–90%"].mean(), "weather only": g["in weather-only 10–90%"].mean()})
    return pd.DataFrame(rows)


def pit(scored: pd.DataFrame, percentiles=PIT_PERCENTILES) -> pd.DataFrame:
    """Where each actual fell among the forecast's stored percentiles: the share in each band (below P05,
    P05–P10, …, above P95) against the share it should be. A calibrated forecast matches the expected
    shares; too many in the middle means the range is too wide, too many at the ends too narrow."""
    cols = [f"p{q:02d}" for q in percentiles]
    values = scored[cols].to_numpy()
    band = (values < scored["actual"].to_numpy()[:, None]).sum(axis=1)   # 0 .. len(percentiles)
    edges = (0, *percentiles, 100)
    labels = [f"below P{percentiles[0]:02d}"] + [f"P{a:02d}–P{b:02d}" for a, b in zip(percentiles, percentiles[1:])] \
        + [f"above P{percentiles[-1]}"]
    counts = np.bincount(band, minlength=len(labels))
    return pd.DataFrame({"band": labels, "observed": counts / max(len(band), 1),
                         "expected": np.diff(edges) / 100, "days": counts})


def bias_by_lead(scored: pd.DataFrame) -> pd.DataFrame:
    """Per lead day: the median forecast's mean and median error, % of demand (positive: forecast too high)."""
    return (scored.groupby("lead_days")["error %"].agg(["mean", "median", "size"])
            .rename(columns={"size": "n"}).reset_index())


# ---------------------------------------------------------------- the weather alone: members against ERA5

def member_weather(run_date, fits, inputs, store=None, ldzs=LDZS) -> pd.DataFrame:
    """One run: per LDZ, member and gas day, the member's heating-hours temperature and its CWV under the
    final model (with the warm-up the run had at issue, forecast.history)."""
    run = pd.Timestamp(run_date)
    ens = fc.ensemble(run, store, ldzs)
    past, _ = fc.history(run, inputs, store, ldzs)
    rows = []
    for ldz in ldzs:
        for member, m in ens.xs(ldz, level="ldz").groupby(level="member"):
            m = m.droplevel("member")
            frame = pd.concat([past[ldz], m[["t2m", "ws10", "ssrd"]]])
            frame.index = pd.DatetimeIndex(frame.index)
            cwv = demand.cwv_series(fits[ldz], frame)[-len(m):]
            rows.append(pd.DataFrame({"ldz": ldz, "member": member, "gas_day": pd.DatetimeIndex(m.index),
                                      "t2m": m["t2m"].to_numpy(), "cwv": cwv}))
    out = pd.concat(rows, ignore_index=True)
    out["run_date"] = run.normalize()
    out["lead_days"] = (out["gas_day"] - out["run_date"]).dt.days
    return out


def era5_weather(fits, inputs, ldzs=LDZS) -> pd.DataFrame:
    """Per LDZ and gas day, ERA5's heating-hours temperature and CWV under the final model."""
    rows = []
    for ldz in ldzs:
        f = inputs[ldz]
        rows.append(pd.DataFrame({"ldz": ldz, "gas_day": pd.DatetimeIndex(f.index), "t2m": f["t2m"].to_numpy(),
                                  "cwv": demand.cwv_series(fits[ldz], f)}))
    return pd.concat(rows, ignore_index=True).dropna(subset=["t2m"])


def cached_member_weather(run_dates, fits=None, inputs=None, store=None) -> pd.DataFrame:
    """member_weather() for every run in run_dates, from the per-run cache, computing the runs not yet in it.
    Runs the ensemble can't give (before 13 Oct 2026 there is no solar) are skipped, and remembered as empty."""
    from ldz_demand.config import create_config, resolve_path
    from ldz_demand.data.store import get_store
    from ldz_demand.models import fit as final

    folder = resolve_path(create_config(), "storage", "cache_dir") / CACHE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    frames = []
    for run in sorted(pd.to_datetime(pd.Series(run_dates)).dt.normalize().unique()):
        path = folder / f"{pd.Timestamp(run):%Y-%m-%d}.csv"
        if not path.exists():
            store = store or get_store(create_config())
            fits = fits or final.load()
            inputs = inputs or final.cached_model_inputs(store=store)
            try:
                member_weather(run, fits, inputs, store).to_csv(path, index=False)
                logger.info(f"member weather for the {pd.Timestamp(run):%d %b} run cached")
            except ValueError as exc:
                logger.info(f"no member weather for {pd.Timestamp(run):%d %b}: {exc}")
                pd.DataFrame(columns=["ldz", "member", "gas_day", "t2m", "cwv", "run_date", "lead_days"]).to_csv(path, index=False)
        f = pd.read_csv(path, parse_dates=["gas_day", "run_date"])
        if not f.empty:
            frames.append(f)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def ranks(members: pd.DataFrame, era5: pd.DataFrame, variable: str = "cwv", seed: int = 0) -> pd.DataFrame:
    """Per run, LDZ and gas day with ERA5: ERA5's rank among the members (0: below every member, MEMBERS: above
    every one; ties split at random), the members' mean and spread, and ERA5's value."""
    m = members.dropna(subset=[variable])
    obs = era5.set_index(["ldz", "gas_day"])[variable].rename("era5")
    g = m.groupby(["run_date", "ldz", "gas_day", "lead_days"])[variable]
    out = pd.concat([g.mean().rename("mean"), g.std(ddof=1).rename("sd"), g.size().rename("members")], axis=1)
    out = out.reset_index().join(obs, on=["ldz", "gas_day"]).dropna(subset=["era5"])
    if out.empty:
        return out.assign(rank=pd.Series(dtype=int))
    wide = m.pivot_table(index=["run_date", "ldz", "gas_day"], columns="member", values=variable)
    wide = wide.reindex(pd.MultiIndex.from_frame(out[["run_date", "ldz", "gas_day"]])).to_numpy()
    e = out["era5"].to_numpy()[:, None]
    below, ties = (wide < e).sum(axis=1), (wide == e).sum(axis=1)
    rng = np.random.default_rng(seed)
    out["rank"] = below + np.array([rng.integers(0, t + 1) for t in ties])
    return out


def rank_histogram(r: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    """Ranks 0..MEMBERS grouped into bins of equal width: the share of days in each against the flat share a
    calibrated ensemble gives. U-shaped: too narrow; a dome: too wide; sloping: a warm or cold bias."""
    n_ranks = MEMBERS + 1
    b = np.minimum((r["rank"].to_numpy() * bins) // n_ranks, bins - 1)
    counts = np.bincount(b, minlength=bins)
    width = np.bincount((np.arange(n_ranks) * bins) // n_ranks, minlength=bins)
    return pd.DataFrame({"bin": np.arange(bins), "observed": counts / max(len(b), 1), "expected": width / n_ranks,
                         "days": counts})


def spread_skill(r: pd.DataFrame) -> pd.DataFrame:
    """Per lead day: the members' spread (root mean variance) against the error of their mean (RMSE against
    ERA5), and the mean bias (members' mean − ERA5). For a calibrated ensemble of M members the RMSE is about
    sqrt((M + 1) / M) times the spread: a ratio of spread to RMSE below 1 means too narrow, above 1 too wide."""
    g = r.assign(err=r["mean"] - r["era5"]).groupby("lead_days")
    out = pd.DataFrame({"spread": g["sd"].apply(lambda s: float(np.sqrt((s ** 2).mean()))),
                        "rmse": g["err"].apply(lambda e: float(np.sqrt((e ** 2).mean()))),
                        "bias": g["err"].mean(), "n": g.size()}).reset_index()
    out["ratio"] = out["spread"] * np.sqrt((MEMBERS + 1) / MEMBERS) / out["rmse"]
    return out


def chi2_flat(hist: pd.DataFrame) -> dict:
    """Pearson's chi-squared test of a histogram against its expected shares (assumes independent days: with
    LDZs and runs sharing weather it is optimistic; a guide, not a verdict)."""
    n = int(hist["days"].sum())
    stat, p = stats.chisquare(hist["days"], hist["expected"] * n)
    return dict(n=n, chi2=float(stat), dof=len(hist) - 1, p=float(p))


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m ldz_demand.models.verification").parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from ldz_demand.charts import forecasts as fch

    runs = fch.wide(fc.load_runs())
    actual = fc.actuals(since=runs["run_date"].min())
    scored = fch.verification(runs, actual, "GB")
    scored = scored[~scored["provisional"]]
    t = coverage_test(scored["in 10–90%"], scored["gas_day"])
    logger.info(f"GB: {t['inside']} of {t['n']} inside P10–P90 ({t['share']:.1%}); naive z {t['z']:.2f}, "
                f"cluster-robust t {t['t']:.2f} on {t['dof']} df (p {t['p_cluster']:.4f})")
    members = cached_member_weather(runs["run_date"].unique())
    logger.info(f"member weather: {members['run_date'].nunique() if not members.empty else 0} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
