# Results

*What the experiments in the [methodology](methodology.md) (§6) found. Each section gives the setup,
the scores and what was decided. Numbers are from `python -m ldz_demand.models.experiment <name>`;
the outputs (predictions, scores, fitted parameters) are written to `data/results/` and not
committed. The choices these results led to: [decisions](decisions.md).*

Last updated: 14 October 2026.

---

## Summary

| | Decision | Evidence |
|---|---|---|
| Weather input | **ERA5 over the LDZ, weighted by gas use** | beats ERA5 at the official station in every LDZ (exp. 1, 3) |
| Seasonal term | **a day-of-year shape shared by all LDZs** (slow heating-season temperature a close second) | cuts GB RMSE from 54.5 to 46.8 GWh/day; −21% on the coldest days (exp. 3) |
| Target | **total − DM, with SE's missing-feed days repaired (target B)** | same scores on shared days; gives SE its 2022/23 and GB a third forward year (exp. 6) |
| Gas-day temperature | **weighted to the heating hours** (06–09, 16–22 double; 23–05 half) | GB RMSE 48.2 → 43.7 GWh/day; holds at the ensemble's 3- and 6-hourly steps (exp. 5) |
| Variables | **temperature, wind, solar**; daily min / max held back | without solar 60.8; min / max add 1.8% on top of the heating-hour weighting, but ERA5 and the ensemble define them differently (exp. 2) |
| Change over time | **training days weighted by recency, half-life 1 year** | best over three forward years, 48.2 vs 48.7 GWh/day per gas year (exp. 6; per gas year led on two years, exp. 4) |
| Against the official CWV | ours is better, mostly in the cold | GB coldest days 64.7 vs 92.6 GWh/day (exp. 3) |
| Against National Gas's day-ahead forecasts | level or better on average, better in winter, worse in summer (not yet like for like) | GB winter 1.9–2.2% vs 3.2–3.6% per gas day |

Current model, per LDZ: demand = a + b · CWV + day of week + bank holiday + Christmas, fitted with
training days weighted by recency (half-life 1 year) so it follows changes in behaviour; CWV from
gas-weighted ERA5 temperature (averaged over the gas day with the heating hours weighted up), wind and
solar, with the shared calendar shape. Target B. All fits use a robust (soft L1) loss.

---

## Setup common to all experiments

- **Target:** total − DM (target A, GWh/day): days whose published total is flagged are left out
  (methodology §3).
- **Data:** gas years 2021/22 to 2025/26 (12 Oct 2021 – 30 Sep 2026). Weather from 1 July 2021, so the
  effective temperatures have warmed up by the first demand day.
- **Scored on the same days for every model.** A day counts only if every model in the experiment was
  scored on it for that LDZ; GB only if all 13 LDZs were.
- **Breaks and regimes.** Where a model's level and slope change on a date (a *break*), a held-out year
  is scored only if each period between breaks it contains has at least 90 training days. Without
  this, SE's post-2022 level was estimated from five odd days — SE's target A is missing for most of
  2022/23 (a feed left out of the published total; methodology §3).
- **Coldest days:** each LDZ's coldest 5% of days by its gas-weighted temperature.
- **Official CWV benchmark:** the published CWV, through the same straight line and calendar terms,
  with a break on 1 Oct 2025 (when its definition changed). It can't be scored on 2025/26 — no
  training days under the new definition — so 2025/26 is reported for our inputs separately.

---

## Experiment 1: weather input

*Which weather input explains demand best, with our CWV form and no seasonal term?* Each gas year held
out in turn.

GB, RMSE in GWh/day (841 days; 2021/22 – 2024/25):

| Input | All | Winter | Coldest | MAPE |
|---|---|---|---|---|
| Official CWV | **99.6** | **145.9** | 175.4 | **5.9%** |
| ERA5, LDZ, area-weighted | 102.3 | 147.8 | 176.8 | 6.5% |
| ERA5, LDZ, gas-weighted | 103.3 | 148.5 | **174.7** | 6.6% |
| ERA5 at the official station | 106.0 | 152.6 | 177.4 | 6.7% |

2025/26 (our inputs only): 57.6 (area), 57.7 (gas), 59.3 (station).

- **The LDZ-wide inputs beat the station in every LDZ.** Gas and area weighting are within about 1%.
- **The official CWV wins at this stage** (8 of 13 LDZs): it has a seasonal term, ours doesn't yet.
- **2021/22 dominates the errors:** every input under-predicts GB by about 100 GWh/day that year
  (RMSE ~147, against ~60 in later years). Demand fell after the 2022 price shock; a model fitted
  mostly on later years can't predict the higher demand before it. Addressed in experiments 3 and 4.
- **Fitted parameters:** the wind-chill threshold W0 sat on its lower bound (wind chill at any wind
  speed) and the cold-weather upturn wanted to start warmer than published. Both settled once the
  seasonal term was added.

---

## Experiment 3: seasonal term

*Does a seasonal term help, and does the station input need more of one?* No seasonal term; a slow
"heating-season" temperature (`S = ys · S−1 + (1 − ys) · T`, mixed in with weight 1 − I1); or a
smooth day-of-year shape (two sine / cosine pairs) shared by all LDZs, its size fitted per LDZ. All
with a level and slope break on 1 Oct 2022, so the seasonal term doesn't stand in for the post-2022
drop in demand. 2021/22 is then the only year before the break and can't be held out.

GB, RMSE in GWh/day (538 days; 2022/23 – 2024/25):

| Model | All | Winter | Coldest | MAPE |
|---|---|---|---|---|
| Official CWV | 49.8 | 67.2 | 92.6 | **4.3%** |
| Gas-weighted, none | 54.5 | 64.3 | 81.5 | 5.3% |
| Gas-weighted, slow | 47.4 | **52.1** | 66.5 | 4.8% |
| **Gas-weighted, calendar** | **46.8** | 52.9 | **64.7** | 4.6% |
| Station, none | 56.3 | 68.9 | 84.0 | 5.3% |
| Station, slow | 48.2 | 53.9 | 66.8 | 4.9% |
| Station, calendar | 47.5 | 56.0 | 67.0 | 4.5% |

2025/26 (our inputs only), gas-weighted: 49.0 calendar, 55.9 slow, 59.6 none.

- **Not comparable with experiment 1's numbers,** which include 2021/22 (the year with the largest
  errors); compare within the table.
- **Both seasonal terms help, most in winter and on cold days.** The calendar shape is best overall
  and beats the official CWV in 10 of 13 LDZs (it loses in NT, WM and SC, narrowly). Our percentage
  error over all days is still slightly higher than the official CWV's: proportionally, our summer
  days are worse.
- **One exception:** on 2025/26's coldest days the model *without* a seasonal term did best (65.5,
  against 73.7 with the calendar shape). One winter, so not decisive; watch it as data accrues.
- **The station needs a larger seasonal term, but not where expected.** The fitted calendar size Sc
  (°C, in CW units) is more negative for the station in 11 of 13 LDZs: −2.6 °C against −2.3 °C on
  average. But WS, where the station runs warmest in winter (methodology §4.2), goes the other way
  (−1.6 vs −2.0), and SO is equal. So the hypothesis that the official seasonal profile partly
  corrects station siting is supported in general (about 15% more seasonal correction), but the
  monthly station offsets don't explain which LDZs need it.
- **The calendar shape is stable:** its coefficients barely change between held-out folds, and it is
  the same for the station and gas-weighted inputs.
- **Fitted parameters are now sensible:** y (effective-temperature memory) about 0.42, close to the
  published 0.43–0.50; W0 about 1.8 m/s; the cold-weather upturn I3 about 0.25, starting below a CW of
  about 8 (published V0 1–5). After widening the bounds on V0 and T0 (see below), few fits sit on a
  bound.

**Identification note.** The calendar term was first written as in the official form,
`I1 · E + (1 − I1) · S` with S = mean temperature + shape. With a free-sized shape this has no unique
solution: the whole CW can be rescaled, with V0–V2, I2 and S0 following, without changing the fit; the
shape's size ran to its bound. It is now written as `E + Sc · g(day of year)`, with g's first cosine
coefficient fixed at 1 — the same model with one free scale fewer.

**Bounds.** V0 was first bounded at published ± 2 and T0 at ≤ 25 °C; most fits sat on those bounds.
Widened to published −3 / +6 and ≤ 35 °C, GB RMSE improved slightly (47.5 → 46.8) and V0 / T0 now sit
on a bound in 14% / 11% of fits.

---

## Experiment 4: change over time

*How should the model follow changes in behaviour?* Holding out a middle year can't test this — a
level per gas year can't be estimated for the year left out, and weighting recent years only makes
sense looking forward. So this experiment is scored **forward**: each of 2023/24, 2024/25 and 2025/26
is predicted from the years before it only, as a forecaster would. Gas-weighted input, calendar shape:

- **fixed:** no break;
- **break 2022:** one level and slope change on 1 Oct 2022;
- **per gas year:** a level and slope per gas year; the forecast uses the latest year's;
- **adapting:** training days weighted by recency, half-life 1 or 2 years, no breaks;
- the official CWV (with the 2022 break) as benchmark.

GB, RMSE in GWh/day. 2023/24 isn't scored for GB: SE has too few training days after the 2022 break.

| Model | 2024/25 | Bias | 2025/26 | Bias | 2024/25 winter | 2024/25 coldest |
|---|---|---|---|---|---|---|
| Official CWV | 56.0 | −7.9 | — | — | 72.0 | 95.7 |
| Fixed | 63.9 | +31.9 | 46.8 | +14.4 | 73.9 | 74.3 |
| Break 2022 | 52.4 | −3.7 | 49.0 | −10.2 | 59.7 | 75.2 |
| **Per gas year** | **51.6** | +4.2 | 45.1 | −6.2 | **56.4** | 69.0 |
| Adapting, 1 year | 56.7 | +18.3 | 44.1 | −0.9 | 60.3 | **68.3** |
| Adapting, 2 years | 59.3 | +24.7 | **44.0** | +6.0 | 65.2 | 69.5 |

- **No variant wins both years.** The 2022 break and the per-year terms do best in 2024/25, when the
  drop in demand was recent; recency weighting does best in 2025/26.
- **Fixed is biased high** (+32 GWh/day in 2024/25): pre-2022 demand still pulls it up.
- **A single break is now biased low** (−10 GWh/day in 2025/26): demand in 2025/26 was higher than
  the post-2022 average, consistent with some recovery.
- **Per gas year is the most consistent:** best or within about 1 GWh/day of best in both years, with
  small biases. Taken as the provisional choice. Two forward years is a small sample; to revisit as
  2026/27 comes in.

---

## Follow-up: summer and the shoulder months

*Why is our percentage error over all days slightly above the official CWV's?* By month, mid-summer
is close to the official CWV; we lose in the shoulder months (April – June, October). Two causes:

- **The level moves between years.** With a single 2022 break, the GB error keeps one sign for months
  and changes sign between years (excluding SE): +27 to +57 GWh/day in winter 2022/23, down to −52 in
  spring 2024, up to +42 in spring 2025, about −40 in winter 2025/26. This is what the per-year terms
  of experiment 4 address.
- **Spring 2025 is missed by every model,** the official CWV included (+54 GWh/day in April 2025,
  against +64 for ours): demand fell further than the weather explains.

Tested and not adopted (all LDZs, GB RMSE in GWh/day):

| Change | Held out (exp. 3 setup) | Forward (exp. 4, per gas year) |
|---|---|---|
| none (calendar shape, 2 sine / cosine pairs) | 47.7* / **46.8** | **51.6** |
| 3 sine / cosine pairs | 47.2* | — |
| calendar shape + slow temperature | 47.6* | — |
| summer level of its own, changing per year | 47.1 | 52.2 |

\* including 2025/26 (884 days, no official benchmark); the others on the experiment's usual days.

- **More detail in the shape** helps by about 1%: within noise; kept at two pairs.
- **The summer level** (an intercept on a weight that is 0 on heating days and 1 above the summer
  cut-off, so summer demand can move independently of the heating line) halves the July – August bias
  in 2024/25 (+18 → +10 GWh/day) and helps October, but makes April – May worse; no net gain.

The shoulder months remain the model's weakest point, shared in spring with the official CWV.

---

## Follow-up: the cold end

*Is the cold-weather upturn right, and why did 2025/26's coldest days favour the model without a
seasonal term?* Gas-weighted input, calendar shape, four forms of the upturn (methodology §5.5):
fitted as now (V0 and I3 free, I3 ≤ max(0.4, 2 × published)); "strong" (I3 up to 1.5); linear (no
upturn); the published V0 and I3. All five gas years, so 2025/26 is included (no official benchmark).

GB RMSE in GWh/day:

| Upturn | Held out: all | Held out: coldest | Forward (per year): all | Forward: coldest |
|---|---|---|---|---|
| **fitted** | **47.7** | **68.1** | **48.4** | **65.2** |
| strong | 47.7 | 68.4 | 48.4 | 65.3 |
| published | 48.8 | 70.2 | 49.5 | 66.8 |
| linear (none) | 49.4 | 75.4 | 50.0 | 72.2 |
| *no seasonal term, fitted upturn* | 56.5 | 76.1 | 55.3 | 76.1 |

- **The upturn is real:** without it, cold-day errors are 10% higher.
- **Fitted beats published**, and allowing a stronger one changes nothing — the bound isn't binding.
  Fitted, it starts at a CW of about 7–8 with I3 about 0.25; published, 1–5 and 0.02–0.34.
- **Extreme cold can't be calibrated from five years.** Below −2 °C (gas-weighted) there are only
  10–18 LDZ-days per year, and the error there changes sign between years (+5.4, −7.3, −5.9 GWh/day
  per LDZ-day in 2023/24 – 2025/26, forward). Treat forecasts for such days with caution.
- **2025/26 is a level effect, not the upturn.** The calendar model's extra under-prediction in
  2025/26 is on ordinary cold days, 0 – 4 °C (−3.5 against −1.1 GWh/day per LDZ-day without a
  seasonal term), not at the extreme; the "coldest 5%" are mostly such days. It is the same higher
  2025/26 winter level seen in the shoulder-month follow-up.

Kept: the fitted upturn, as is.

---

## Against National Gas's day-ahead forecasts

*How does the model compare with the forecasts National Gas actually publishes* — not the official
CWV regressed on demand, but their total-demand forecast per LDZ (`ng_forecast_daily`)? Their first
day-ahead issue (12:58 on D−1) against the final model (scored forward, `experiment final`), both on
total demand in GWh: ours is our prediction plus the actual DM, so its error is the same as on our
target. Run with `python -m ldz_demand.models.benchmark`. GB on days all 13 LDZs are scored (2023/24:
from February 2024, after SE's repaired days).

GB, absolute % error per gas day on total demand, and RMSE in GWh/day (final model; first written with
experiment 4's per-gas-year model, which was slightly behind it):

| | 2023/24 NG | 2023/24 ours | 2024/25 NG | 2024/25 ours | 2025/26 NG | 2025/26 ours |
|---|---|---|---|---|---|---|
| All days | **3.1%** | 3.3% | 3.6% | **3.3%** | 3.3% | **3.2%** |
| Winter (Nov – Mar) | 2.5% | 2.5% | 3.6% | **2.2%** | 3.2% | **1.9%** |
| Summer | **3.3%** | 3.5% | **3.6%** | 4.1% | **3.4%** | 4.2% |
| RMSE, all days | 40.8 | **38.1** | 61.6 | **50.6** | 56.8 | **39.9** |

(Percentages are lower than on our target, as total demand includes DM.)

**Not like for like, in two directions:**

- **Weather — in our favour:** ours uses actual weather, theirs a day-ahead forecast. At day-ahead
  this matters little: their forecast CWV is 0.31 °C RMSE from the actual, and removing the part of
  their error that follows it lowers their LDZ RMSE by only 1 – 13%.
- **DM — in theirs:** their forecast is total demand, so includes forecasting DM; ours uses the actual
  DM. Their DM forecasts aren't published, so this can't be separated; it may explain their much larger
  errors in SE (RMSE 11.7 against our 5.7 GWh/day) and WS (7.0 against 2.7).

**Findings:**

- **Winter: ours is clearly better** in the two full winters, 1.9 – 2.2% against 3.2 – 3.6% per gas
  day (level in the part of winter 2023/24 that can be scored).
- **Summer: theirs is better,** 3.3 – 3.6% against 3.5 – 4.2% — the shoulder-month weakness again.
- **Overall: level or better on % error, RMSE 7 – 30% lower for ours** (the RMSE is dominated by
  high-demand days).
- **The like-for-like test** is our model on the ECMWF ensemble at the same issue time; it needs an
  ensemble archive covering at least one winter (the backfill).

---

## Experiment 6: target A vs B

*Does repairing the days a feed is missing from the published total help?* Target A (total − DM on
days the total passes the checks) against target B (as A, plus days where the total left out a feed,
repaired as offtakes + the feed's usual level; methodology §3). In practice only SE: B adds its
Sep 2022 – Feb 2024 days. Scored forward, gas-weighted input, calendar shape.

The repaired days' "actual" is our own repair, so scoring on them would partly score the repair
against itself. **Scores use only days that are real in both targets;** repaired days are reported
separately.

- **On the same days, A and B score the same** (GB 2024/25: per gas year 51.6 vs 52.2, break 2022
  52.4 vs 53.7), except recency weighting in SE (RMSE 11.3 → 7.2): with A it had almost no SE data
  after 2022 to weight.
- **B gives GB a third forward year.** With A, 2023/24 can't be scored for GB (SE has ~5 training days
  after the 2022 break); with B it can, and the ranking changes:

GB, real days, 2023/24 – 2025/26 (882 days), RMSE in GWh/day:

| Model (target B) | All | Winter | Coldest | MAPE | 2023/24 | 2024/25 | 2025/26 |
|---|---|---|---|---|---|---|---|
| **Recency weighting, half-life 1 year** | **48.2** | **54.9** | 64.4 | **4.55%** | 39.5 | 56.4 | 44.1 |
| Recency, half-life 0.5 year | 48.9 | 55.9 | 68.8 | 4.56% | **38.3** | 57.0 | 45.9 |
| Recency, half-life 1.5 years | 48.5 | 55.7 | 63.4 | 4.59% | 40.4 | 56.9 | **43.9** |
| Recency, half-life 2 years | 48.9 | 56.5 | **63.4** | 4.60% | 40.7 | 57.6 | 44.0 |
| Per gas year | 48.7 | 55.3 | 65.6 | 4.80% | 48.6 | **52.2** | 45.2 |
| Per gas year + recency, 1 year | 49.0 | 55.9 | 67.0 | 4.72% | 46.8 | 54.4 | 44.6 |
| Break 2022 + recency, 1 year | 50.0 | 59.0 | 74.5 | 4.76% | 46.8 | 54.9 | 46.7 |
| Break 2022 | 51.0 | 61.3 | 78.4 | 4.90% | 48.6 | 53.7 | 49.5 |

- **2023/24 is why.** Demand rose from 2022/23 — the year of the biggest cut after the price shock — so
  carrying the latest year's level forward under-predicts by 28 GWh/day; recency weighting smooths
  across years. Per gas year still wins 2024/25, when the latest year was the better guide.
- **Half-life 1 year** is best overall and in winter; longer half-lives are marginally better on the
  coldest days only.
- **Experiment 3 holds on target B** (held out, 2022 break): calendar shape 47.2, slow temperature
  47.7, no seasonal term 54.8, station with calendar 48.1, official CWV 49.9 GWh/day.
- **Repaired days** (175 SE days in the scored years) have RMSE ~10.3 GWh/day per LDZ-day, against ~6
  on SE's real days: the repair is rougher than measured data, as expected — fine for training, not for
  scoring.

Chosen: **target B, recency weighting with a 1-year half-life.** It also needs no hand-picked break
dates. Experiment 6 is `python -m ldz_demand.models.experiment target`.

---

## Experiments 2 and 5: variables and the gas-day temperature

*Which weather variables earn their place, and how should the hours of a gas day be averaged?* The
model chosen after experiment 6 (target B, recency weighting, calendar shape), scored forward on
2023/24 – 2025/26 (GB 882 days). Run with `python -m ldz_demand.models.experiment variables` and
`… averaging`.

- **Experiment 2, variables:** the current inputs; without solar (S0 = 0); and with the day's minimum
  and maximum temperature, the CWV's temperature becoming `T = mean + m_min·(min − mean) +
  m_max·(max − mean)` with both weights fitted (0 – 1).
- **Experiment 5, gas-day averaging,** from the hourly table: a flat mean of the gas day's hours; and
  a heating-hours profile — 06–09 and 16–22 UK time count double, 23–05 half (`models/averaging.py`).
  Each also from every third hour, interpolated back, as the ensemble gives (3-hourly to day 6, then
  6-hourly).

GB, RMSE in GWh/day:

| Gas-day temperature | All | Winter | Coldest | MAPE |
|---|---|---|---|---|
| Flat mean (current; daily table) | 48.2 | 54.9 | 64.4 | 4.55% |
| Flat mean, from hourly / 3-hourly | 48.3 / 48.3 | 55.0 / 54.9 | 64.5 / 64.7 | 4.57% / 4.56% |
| Without solar | 60.8 | 66.5 | 70.4 | 5.44% |
| With min / max | 45.0 | 52.2 | 60.5 | 4.27% |
| **Heating hours, hourly** | **43.75** | **49.4** | **61.4** | **4.29%** |
| Heating hours, 3-hourly | 43.72 | 49.2 | 61.3 | 4.28% |
| Heating hours, 6-hourly | 44.4 | 49.3 | 60.7 | 4.34% |
| Heating hours (3-hourly) + min / max | 42.95 | 48.75 | 59.5 | 4.17% |

- **Weighting the heating hours is the largest single gain since the seasonal term:** −9% overall,
  −10% in winter, in every LDZ. It moves the gas day's temperature by +0.3 °C on average (heating hours
  are warmer than the night), ±0.3 °C day to day.
- **It survives the forecast's resolution:** the same gain from 3-hourly steps, most of it (−8%) from
  6-hourly.
- **Solar matters:** without it, RMSE is 26% higher.
- **Min / max say the same thing:** the fit puts more weight on the day's maximum (median 0.28) than its
  minimum (0.11) — night-time temperature matters less to demand than the day's. On top of the
  heating-hours profile they add only 1.8%.
- **Min / max held back:** in ERA5 they are the extremes of the hourly values; in the ensemble they come
  from its own period minimum / maximum (`mn2t` / `mx2t`), which run colder / warmer. A model trained on
  one and run on the other would be off at exactly the days it leans on. Revisit with a consistent
  definition (e.g. both from the temperature at the ensemble's steps).

Chosen: **temperature averaged with the heating-hours profile; solar kept; min / max not used.**

---

## The final model

Fitted on every usable day of 2021/22 – 2025/26 (about 1,800 per LDZ, target B), all 13 LDZs together:
`python -m ldz_demand.models.fit`, saved with the package as `src/ldz_demand/models/data/final_fit.csv`
(one row per LDZ: CWV parameters, linear terms, the shared shape). `models.fit.load()` rebuilds the
fitted models for prediction; they expect the heating-hours gas-day temperature (`models.averaging`).

- **All 13 converged.** In-sample RMSE (all training days, unweighted) 0.9 (WN) – 9.7 (NW) GWh/day.
- **The cold-weather upturn sits on its bound in 8 of 13 LDZs** (I3 = 0.4). Only the final fit sees
  2025/26 — January 2026's cold spell, weighted most as the latest year — and it wants a stronger upturn
  than any forward fold did (median 0.28, never at the bound). With the bound raised to 1.5, I3 comes out
  0.27 – 0.60, but the coldest days barely change (bias within 0.3, RMSE within 0.1 GWh/day per LDZ-day),
  and forward scores are identical. **Kept at the bound:** a deliberate guard with few cold days in five
  years; to revisit as cold winters accrue.

---

## Open

- **Shoulder months** (see above): spring 2025 in particular.
- **Winter 2025/26 level:** demand above every model's forecast in ordinary cold days; watch 2026/27.
- **Daily min / max on a definition shared by ERA5 and the ensemble** (experiment 2).
- **The heating-hours profile is fixed,** not fitted: its weights could be estimated (e.g. per LDZ).
- **The cold-weather upturn's bound** binds in the final fit (see above).
- **Against National Gas's forecasts, like for like** — our model on the ensemble (needs the archive
  backfill).
