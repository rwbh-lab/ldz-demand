# Challenger models and the feature search

*Two checks on the final model (the CWV model in [methodology](methodology.md) §5, scored in
[results](results.md)): what its errors say it is missing, and whether a different kind of model, given
the same inputs, does better. Numbers from `python -m ldz_demand.models.diagnostics` and
`python -m ldz_demand.models.experiment features | challenger`; outputs in `data/results/`, not committed.*

Last updated: 12 November 2026.

**Status: not on the dashboard yet.** Both parts are to go on the dashboard (see
[the last section](#for-the-dashboard)); building the pages is parked.

---

## Summary

| Question | Answer | Evidence |
|---|---|---|
| Is anything systematic left in the final model's errors? | **Two small things:** the weekend dip deepens with the cold; bridge days | each leans the same way in all three held-out years; nothing else the tree found does |
| Do they help? | **Yes: GB RMSE 43.7 → 41.8 GWh/day** (−4.5%), coldest days 61.3 → 56.2 | better in every year; almost all from the weekend term |
| Does a flexible ML model on the same inputs beat the CWV form? | **No.** An Explainable Boosting Machine reaches the official CWV's level, not ours | GB RMSE 51.9 vs 46.0 (ours) and 50.7 (official CWV) |
| What is the CWV form worth over a textbook model? | **Most of the accuracy** | degree-day regression 179, no weather at all 219 |

**So: keep working on the CWV model.** The ML challenger found nothing the CWV form misses beyond what
the error analysis found, and gained less than the CWV model did from the same two features.

---

## Setup common to both parts

As the experiments in [results](results.md): target B, ERA5 inputs as the final model (gas-weighted,
heating-hours temperature), training days weighted by recency (half-life 1 year), scored **forward**:
2023/24, 2024/25 and 2025/26 each predicted from the gas years before it only. Every model gets the
same folds, the same training days and the same target (`Model.family` in `models.experiment`). GB is
the sum of the 13 LDZs, scored on days where every LDZ has a prediction; days whose total was repaired
are left out (their "actual" is our repair).

---

## Part 1: finding features from the errors

### Method

A shallow regression tree (depth 3, leaves of at least 2% of the rows) on the final model's forward
errors, in % of each LDZ's mean demand so the 13 LDZs share one tree (`models.diagnostics`). The tree
doesn't forecast: it looks for groups of days where the errors lean one way, using the model's own
inputs and candidates it lacks. Every candidate must exist at forecast time — in the ECMWF ensemble
(temperature, wind, solar, precipitation, daily min / max) or known in advance (the calendar):

- temperature: today's, the two days before, the day-to-day change, the previous week's mean, the
  length of a cold spell (consecutive days below 3 °C), daily min / max and their range;
- wind, solar, precipitation;
- calendar: day of the gas year, month, weekday, bank holidays, Christmas, bridge days, school holidays
  (approximate England dates: October and February half-terms, Easter);
- the LDZ and the gas year (drift, not a usable feature).

Then two checks before believing a split:

1. **Grown on two years, scored on the third.** A split that is real should explain part of the third
   year's errors.
2. **Each candidate group year by year:** its mean error minus the rest's, after taking out each
   LDZ-year's level. Worth testing only if every year leans the same way.

### What the errors look like

- **Size:** RMSE 5.9% of mean demand per LDZ-day.
- **Drift between years:** the mean error falls from +1.3% (2023/24) to +0.8% to +0.05% (2025/26) as
  the recency weighting catches up with changes in behaviour. Taking each LDZ-year's level out only
  lowers the RMSE to 5.65%.
- **Persistence:** about half of each day's error is still there the next day (lag-1 autocorrelation
  0.40–0.70; SC 0.70, WM 0.61). That is slow-moving behaviour, not weather: only the last days' actual
  demand would capture it, which isn't available at forecast time beyond the next day.
- **Grown on two years, scored on the third, the tree explains nothing** (−35%, −31%, −9% of the
  variance: worse than predicting no error), and its first split changes every year.

### The candidates, year by year

The error of each group against the rest, % of mean demand (+: the model too high):

| Group | 2023/24 | 2024/25 | 2025/26 | Same sign every year |
|---|---|---|---|---|
| **Cold weekend vs cold weekday** (warmest hour ≤ 6.5 °C) | +3.5 | +5.0 | +4.4 | **yes** |
| **Bridge day** | +2.2 | +2.8 | +3.3 | **yes** |
| Cold spell (3+ days below 3 °C) | +1.3 | −4.2 | −3.8 | no |
| School holiday (approximate dates) | −1.1 | +3.1 | +1.0 | no |
| First half of October vs 16–23 October | +1.6 | −1.9 | −3.2 | no |

Precipitation and the daily min / max showed no stable pattern.

### The two features

- **Weekend × cold** (`weekend_cwv`): a weekend flag times the CWV, added to the model's design. The
  final model gives Saturday and Sunday a fixed offset whatever the weather; the errors say the weekend
  dip deepens with the cold — offices, shops and industry heat on weekdays and switch off at weekends,
  which matters little on a mild day and a lot on a cold one. Its fitted coefficient has that sign
  (weekend demand rises less with the cold).
- **Bridge days** (`bridge`, `calendar.bridge`): working days next to a bank holiday, or with a day off
  on both sides (the Thursday before Good Friday, the Tuesday after Easter Monday, a Friday after New
  Year's Day). Many people take them as leave. About 7 a year.

### Scores

GB RMSE, GWh/day, forward, 882 days (`experiment features`):

| | All | Winter | Coldest 5% | MAPE | 2023/24 | 2024/25 | 2025/26 |
|---|---|---|---|---|---|---|---|
| final | 43.7 | 49.4 | 61.3 | 4.29% | 37.8 | 50.4 | 39.9 |
| final + bridge | 43.6 | 49.3 | 61.1 | 4.28% | 37.5 | 50.3 | 39.7 |
| final + weekend | 41.9 | 46.8 | 56.7 | 3.97% | 36.6 | 48.6 | 37.8 |
| **final + both** | **41.8** | **46.6** | **56.2** | **3.96%** | **36.4** | **48.5** | **37.5** |

Bridge days barely move the totals — there are only 22 in the three years — but on those days the GB
over-forecast falls from +28 to +11 GWh/day.

**Caveat:** the two features were chosen by looking at the errors of these same three years, so the
gain is somewhat optimistic. Each held in every year separately, and the weekend one has a clear
physical reason. The clean test is data the choice never saw: the 2025/26 ensemble backfill run as
forecasts, then winter 2026/27's live runs.

**Not yet in the live model.** Adopting them means setting the extras in `models.fit`, refitting,
regenerating the model-error pool behind the P10–P90 intervals, and rebuilding the NAS image — after
the backfill test.

---

## Part 2: the challenger models

### The models

| Model | What it is | Module |
|---|---|---|
| climatology | no weather: the mean demand of the training days within ±7 days of the day of the gas year, plus a weekday offset | `models.climatology` |
| control | the textbook degree-day regression: demand = a + b · max(15.5 − T, 0) + weekday + bank holiday + Christmas, on the flat daily mean temperature; the 15.5 °C base fixed, not fitted | `models.control` |
| EBM | an Explainable Boosting Machine on the final model's raw inputs (below) | `models.ebm` |
| official CWV | the published CWV through the same straight line (no 2025/26: its definition changed on 1 Oct 2025) | `models.demand` |
| final | the live model | `models.demand` |

**The EBM** (the `interpret` package) is an additive model fitted by boosting: one curve per input
plus up to 10 pairwise interactions, each of which can be drawn, so it stays interpretable — the
reason it was chosen over gradient boosting. Its inputs are the CWV model's before its engineering
(`models.features`): the heating-hours temperature and the two days before it, wind, solar, the time
of year, weekday, bank holiday, Christmas, and the LDZ. One model for the 13 LDZs, each LDZ's target
divided by its mean demand. Demand may only fall as temperature and solar rise and only rise with wind.
Settings chosen on the 2024/25 fold alone, before 2025/26 was scored. Three things learned on the way:

- `interpret`'s own monotone constraints stop the boosting almost at once (5% error on a noise-free
  curve); instead the model is fitted freely and each of those curves then made monotone
  (`monotonize`).
- A day-by-day season curve overfits — with three or four training years it learns those winters'
  weather as "season". The time of year goes in as 30-day blocks (tuning fold GB RMSE 62 → 55).
- 10 interactions beat 0 or 25; the learning rate and leaf size made no difference.

### Scores

GB, GWh/day, forward. 2023/24 and 2024/25 (the 536 days every model, the official CWV included, was
scored on), and 2025/26 alone:

| | All | Winter | Coldest 5% | MAPE | 2025/26 all | 2025/26 coldest | 2025/26 MAPE |
|---|---|---|---|---|---|---|---|
| climatology | 219 | 315 | 422 | 16.1% | 217 | 436 | 16.0% |
| control | 179 | 201 | 157 | 14.7% | 196 | 183 | 14.2% |
| EBM | 52 | 67 | 64 | 4.8% | 46 | 72 | 3.96% |
| official CWV | 51 | 67 | 92 | 4.5% | — | — | — |
| **final** | **46** | **52** | 65 | **4.3%** | **40** | **53** | 4.26% |

### What it says

- **Weather beats no weather, but the textbook line captures little of it.** The control's error has a
  seasonal pattern: about 12 GWh/day too low per LDZ in December–February and too high in April–May,
  the same way in every LDZ, so it adds up at GB level. A degree-day line can't tell a cold January
  day from an equally cold April one; the CWV's seasonal term is its largest single refinement.
- **The EBM, from the raw inputs, reaches the official CWV's level** and is far better on cold days
  (64 vs 92), **but not ours.** It is behind in every LDZ, by about 20%.
- **Its one edge is warm days.** By temperature band (all three years), the final model is better in
  every heating band, cold included; the EBM is better only above 14 °C, and only in 2025/26 — low
  demand, where its lower MAPE in 2025/26 comes from.
- **Blending adds little.** Their GB errors correlate at 0.7; a plain 50/50 average is about 2% better
  than the final model, not in every year — not worth running a second model in the daily job.
- For completeness: the EBM was also given the two features from part 1. It gained less from them
  than the CWV model did, and was not kept.

**The CWV form is strong. Further work goes into the CWV model, not a replacement for it.**

---

## For the dashboard

To build (parked; nothing on the dashboard yet). Two stories, kept apart:

1. **Finding features from the errors** — the method in brief (tree → year-by-year check); the
   candidates table with the two that held; the error persistence; the scores table with and without
   the features; the caveat and the pending backfill test.
2. **The challenger** — the ladder of models (climatology → control → official CWV → EBM → ours) as one
   chart of GB RMSE (all, winter, coldest); the control's seasonal bias by month; the EBM's curves
   (temperature, time of year, weekday) as the interpretable view of what it learned; who wins by
   temperature band; the conclusion.

The results are written by the commands at the top; the dashboard needs compact copies of them
shipped with the package, as `models.results` does for the experiments.
