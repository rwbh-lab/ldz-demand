# Results

*What the experiments in the [methodology](methodology.md) (§6) found. Each section gives the setup,
the scores and what was decided. Numbers are from `python -m ldz_demand.models.experiment <name>`;
the outputs (predictions, scores, fitted parameters) are written to `data/results/` and not
committed.*

Last updated: 13 October 2026.

---

## Summary

| | Decision | Evidence |
|---|---|---|
| Weather input | **ERA5 over the LDZ, weighted by gas use** | beats ERA5 at the official station in every LDZ (exp. 1, 3) |
| Seasonal term | **a day-of-year shape shared by all LDZs** (slow heating-season temperature a close second) | cuts GB RMSE from 54.5 to 46.8 GWh/day; −21% on the coldest days (exp. 3) |
| Change over time | **level and slope per gas year, latest year forward** (provisional) | best or near-best in both forward years (exp. 4) |
| Against the official CWV | ours is better, mostly in the cold | GB coldest days 64.7 vs 92.6 GWh/day (exp. 3) |

Current model, per LDZ: demand = a + b · CWV + day of week + bank holiday + Christmas, with a and b
allowed to change each gas year; CWV from gas-weighted ERA5 temperature, wind and solar, with the
shared calendar shape. All fits use a robust (soft L1) loss.

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

## Open

- **Summer errors:** proportionally larger than the official CWV's (MAPE); check the summer cut-off
  (V1, V2, q) and low-demand days.
- **Cold end:** 2025/26's coldest days favoured no seasonal term; few cold days in five years
  (methodology §5.5).
- **Remaining experiments:** variables (2), gas-day averaging (5), target A vs B (6) — B would give
  SE its 2022/23 days.
- **Against National Gas's forecasts** (methodology §7), once the model is run on the ensemble.
