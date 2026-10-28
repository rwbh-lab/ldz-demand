# Decisions

*Each modelling choice in one place: what was chosen, instead of what, why, the evidence, and what
would make us look again. The [methodology](methodology.md) describes how the model works; the
[results](results.md) give the scores behind these choices. Grouped in the order of the dashboard's
Project map: data, pre-CWV models, the CWV model, validation.*

Last updated: 14 October 2026.

---

## Index

| | Decision | Chosen |
|---|---|---|
| **Data** | [D1](#d1-demand-national-gas-only-five-years) Demand source | National Gas data portal; its rolling five years |
| | [D2](#d2-d6-close-out-values) Which values | D+6 close-out |
| | [D3](#d3-weather-era5-reanalysis) Weather | ERA5 reanalysis, gridded |
| | [D4](#d4-forecasts-the-ecmwf-ensemble-00z-15-days) Forecasts | ECMWF ensemble, 00z, 15 days, cropped on download |
| **Pre-CWV models** | [P1](#p1-target-total--dm-not-ndm) Target | total − DM, not published NDM |
| | [P2](#p2-repair-the-se-missing-feed-target-b) Bad totals | flag; repair SE's missing feed (target B) |
| | [P3](#p3-ldz-map-postcode-sampled) LDZ map | postcode-sampled |
| | [P4](#p4-weight-by-gas-use) Weighting | by gas use |
| | [P5](#p5-gas-day-temperature-weighted-to-the-heating-hours) Gas-day temperature | weighted to the heating hours |
| | [P6](#p6-variables-temperature-wind-solar) Variables | temperature, wind, solar |
| **CWV model** | [C1](#c1-keep-the-official-cwvs-structure) Form | the official CWV's structure, refitted |
| | [C2](#c2-a-seasonal-shape-shared-by-all-ldzs) Seasonal term | a smooth shape shared by all LDZs |
| | [C3](#c3-write-the-shape-as-e--sc--g) How it's written | `E + Sc · g`, not `I1 · E + (1 − I1) · S` |
| | [C4](#c4-a-fitted-cold-weather-upturn-bounded) Cold end | fitted upturn, bounded |
| | [C5](#c5-no-separate-summer-level) Summer | no separate summer level |
| | [C6](#c6-demand-linear-in-the-cwv-plus-calendar-terms) Demand | linear in the CWV, plus calendar terms |
| | [C7](#c7-follow-behaviour-by-weighting-recent-years) Change over time | recency weighting, half-life 1 year |
| | [C8](#c8-a-robust-loss-bounds-near-the-published-values) Fitting | robust loss; bounds near the published values |
| | [C9](#c9-fit-all-ldzs-together) Pooling | all LDZs in one fit |
| **Validation** | [V1](#v1-score-on-held-out-years-forward-where-time-matters) Scheme | held-out gas years; forward where time matters |
| | [V2](#v2-the-same-days-for-every-model) Comparisons | the same days for every model |
| | [V3](#v3-a-regime-needs-90-training-days) Breaks | a regime needs 90 training days |
| | [V4](#v4-benchmarks-the-official-cwv-and-national-gass-forecasts) Benchmarks | official CWV, same regression; National Gas's own forecasts |
| **Not used (yet)** | [N1](#n1-prices) Prices · [N2](#n2-daily-min--max-temperature) min / max · [N3](#n3-precipitation) precipitation | |

---

## Data

### D1. Demand: National Gas only, five years

- **Chosen:** LDZ demand, DM, NDM, calorific value, CWV and NTS offtakes from the National Gas data
  portal — free, no key.
- **Instead of:** longer history from other sources.
- **Why:** it is the only public source of daily LDZ demand; the portal keeps a rolling five years
  (from 12 October 2021).
- **Cost:** five years hold the 2022 behaviour change and few cold winters — the main limit on every
  finding ([methodology §9](methodology.md#9-caveats)).
- **Revisit if:** older daily LDZ demand becomes available.

### D2. D+6 close-out values

- **Chosen:** each day's values as closed out six days later.
- **Instead of:** the first (D+1) publication.
- **Why:** D+1 values are revised; D+6 are the settled ones. The most recent ~6 days are left out of
  modelling until they close out.

### D3. Weather: ERA5 reanalysis

- **Chosen:** ERA5 hourly reanalysis on its 0.25° grid, averaged over each LDZ.
- **Instead of:** observations at the official weather stations.
- **Why:** gridded weather can follow where gas is used across an LDZ rather than one point; it is
  free, consistent through time, and on the same grid as the ensemble forecasts, so the model sees the
  same kind of weather in training and in forecasting.
- **Evidence:** ERA5 over the LDZ beats ERA5 at the official station in every LDZ (results, exp. [1](results.md#experiment-1-weather-input), [3](results.md#experiment-3-seasonal-term)).
- **Caveat:** reanalysis is a model of the weather, not a measurement.

### D4. Forecasts: the ECMWF ensemble, 00z, 15 days

- **Chosen:** the 00z run of the ECMWF open-data ensemble (50 members), out to 15 days, cropped to GB
  as each step downloads; archived by the daily scheduled job.
- **Instead of:** a deterministic forecast; the 12z run; storing global files.
- **Why:** 50 members give a demand distribution, not a point, and its shape matters (a cold tail lifts
  expected demand); 15 days covers the gas prompt window despite lower skill at long leads; cropping
  keeps a run to GB-size files.
- **Note:** the open data has no control member — 50 perturbed members only.

---

## Pre-CWV models

### P1. Target: total − DM, not NDM

- **Chosen:** total LDZ demand minus daily-metered demand, in GWh — NDM plus unidentified gas and
  shrinkage: the weather-sensitive part.
- **Instead of:** published NDM.
- **Why:** published NDM is itself calculated from the CWV, so fitting a CWV to it would be circular.
- **Evidence:** [methodology §3](methodology.md#3-target); no step changes from sites changing metering class (checked).
- **Revisit if:** a measured NDM series appears.

### P2. Repair the SE missing feed (target B)

- **Chosen:** flag bad published totals (invalid, mismatched with the NTS offtakes, a feed left out);
  drop flagged days, except days where SE's non-NTS feed is missing from the total, which are repaired
  as offtakes + that feed's usual level (target B).
- **Instead of:** dropping them too (target A).
- **Why:** dropping them leaves SE almost no data for 2022/23; the repair gives it back, and gives GB a
  third forward test year. On days real in both, A and B score the same.
- **Evidence:** [results, experiment 6](results.md#experiment-6-target-a-vs-b). Repaired days are rougher (RMSE ~10 vs ~6 GWh/day), so they are
  used for training, never for scoring (V2).

### P3. LDZ map: postcode-sampled

- **Chosen:** LDZ membership from local authorities, with authorities on an LDZ boundary split by
  sampling their postcodes against the gas network operators' own postcode checkers.
- **Instead of:** whole-authority labels, Voronoi cells around listed towns, or a hybrid.
- **Why:** there is no public LDZ boundary file; this one matches measured LDZ gas use most closely
  (mean gap 0.50 percentage points of GB gas use).
- **Evidence:** [methodology §4.1](methodology.md#41-which-places-belong-to-which-ldz). The choice barely matters for weather (0.01 – 0.05 °C day to day).

### P4. Weight by gas use

- **Chosen:** each grid cell weighted by DESNZ gas consumption of the places in it.
- **Instead of:** by land area, or the official station's grid point.
- **Why:** demand comes from where gas is used, not from where the land is.
- **Evidence:** weighting moves LDZ temperature 0.1 – 0.45 °C day to day ([methodology §4.2](methodology.md#42-how-places-inside-an-ldz-are-weighted)); in the
  model, gas and area weighting are within ~1% (exp. 1) — kept for the reason, not the score.

### P5. Gas-day temperature weighted to the heating hours

- **Chosen:** the gas day's temperature as a weighted mean of its hours: 06–09 and 16–22 UK time
  double, 23–05 half.
- **Instead of:** a flat mean over the 05:00 – 05:00 gas day.
- **Why:** heating, and so demand, follows the morning and evening; night-time temperature matters
  less.
- **Evidence:** −9% GB RMSE (48.2 → 43.7 GWh/day), in every LDZ; the gain survives the ensemble's 3-
  and 6-hourly steps ([results, exp. 5](results.md#experiments-2-and-5-variables-and-the-gas-day-temperature)).
- **Revisit:** the weights are fixed, not fitted.

### P6. Variables: temperature, wind, solar

- **Chosen:** temperature, wind speed (through wind chill) and solar radiation.
- **Why:** the official CWV uses the same three since October 2025; without solar the model is 26%
  worse (exp. 2).
- **Not used:** daily min / max (N2), precipitation (N3).

---

## CWV model

### C1. Keep the official CWV's structure

- **Chosen:** the official CWV's form — effective temperature, wind chill, solar, a seasonal term, a
  summer cut-off and a cold-weather upturn — with every parameter refitted per LDZ to our weather.
- **Instead of:** a free-form or machine-learned weather–demand model.
- **Why:** each part has a physical meaning and a published value to compare with; the result is
  directly comparable with the official CWV; and five years is little data for a flexible model.

### C2. A seasonal shape shared by all LDZs

- **Chosen:** a smooth day-of-year shape (two sine / cosine pairs), the same for all LDZs, its size
  fitted per LDZ.
- **Instead of:** the official pseudo seasonal normal (not public); no seasonal term; a slow
  "heating-season" temperature.
- **Why:** behaviour has a seasonal pattern beyond the weather (heating on in autumn, left on into
  spring); one shape for all 13 LDZs gives it ~13 times the data.
- **Evidence:** cuts GB RMSE from 54.5 to 46.8 GWh/day and coldest-day error by a fifth; the slow
  temperature is close behind ([results, exp. 3](results.md#experiment-3-seasonal-term)). Three sine / cosine pairs: within noise.

### C3. Write the shape as `E + Sc · g`

- **Chosen:** `CW = E + Sc · g(day of year) − wind chill + solar`, with g's first cosine coefficient
  fixed at 1.
- **Instead of:** the official form, `I1 · E + (1 − I1) · S`, with S a free-sized shape.
- **Why:** with a free-sized shape the official form has no unique solution — the whole CW can be
  rescaled, with the thresholds following, without changing the fit; the shape's size ran to its bound.
  This is the same model with one free scale fewer.
- **Evidence:** [results, experiment 3](results.md#experiment-3-seasonal-term), identification note.

### C4. A fitted cold-weather upturn, bounded

- **Chosen:** the upturn below V0 fitted per LDZ, its strength I3 bounded at max(0.4, 2 × published).
- **Instead of:** no upturn (linear); the published upturn.
- **Why:** without it, cold-day errors are 10% higher; fitted beats published.
- **Bound kept** although the final fit reaches it in 8 LDZs: only that fit sees January 2026, and
  lifting the bound changes the coldest days by under 0.1 GWh/day RMSE. Extreme cold (< −2 °C) is too
  rare in five years to calibrate.
- **Evidence:** [results, cold-end follow-up](results.md#follow-up-the-cold-end); the final model.

### C5. No separate summer level

- **Rejected:** a summer level of its own (an intercept that switches on above the summer cut-off).
- **Why:** it halves the July – August bias but makes April – May worse; no net gain. The shoulder-month
  errors are mostly the level moving between years (C7).
- **Evidence:** [results, summer follow-up](results.md#follow-up-summer-and-the-shoulder-months).

### C6. Demand linear in the CWV, plus calendar terms

- **Chosen:** demand = a + b · CWV + day of week + bank holiday + Christmas period (24 Dec – 1 Jan).
- **Why:** the CWV's own transform carries the non-linearity; calendar effects are large and well
  known — in the final fit, Saturdays −1 to −11 GWh/day by LDZ, the Christmas period −2 to −17.
- **Detail:** bank holidays from the `holidays` package — England & Wales, Scotland's own for SC.

### C7. Follow behaviour by weighting recent years

- **Chosen:** each training day weighted by its age, half-life 1 year.
- **Instead of:** fixed; a break in autumn 2022; a level and slope per gas year.
- **Why:** demand fell after the 2022 price shock and has partly recovered since; recency weighting
  follows that without hand-picked break dates.
- **Evidence:** best over three forward years (GB 48.2 vs 48.7 GWh/day per gas year, 51.0 for one
  break); per gas year wins one year of three (results, exp. [4](results.md#experiment-4-change-over-time) and [6](results.md#experiment-6-target-a-vs-b)).

### C8. A robust loss; bounds near the published values

- **Chosen:** soft-L1 least squares, scaled per LDZ by a robust error size; CWV parameters bounded in
  physically sensible ranges around the published values.
- **Why:** a few odd days (data errors, one-off events) shouldn't pull the fit; bounds stop parameters
  wandering where five years can't pin them down.
- **History:** V0 and T0 started tighter and sat on their bounds; widened ([results, exp. 3](results.md#experiment-3-seasonal-term), bounds).

### C9. Fit all LDZs together

- **Chosen:** one fit for all 13 LDZs — each with its own parameters, sharing the seasonal shape — each
  LDZ's errors divided by its typical size.
- **Why:** the shared shape needs it; the scaling stops NW and NT deciding the shape.

---

## Validation

### V1. Score on held-out years; forward where time matters

- **Chosen:** leave one gas year out for comparing model forms; forward scoring — each year predicted
  from the years before it only — for change over time and the final choices.
- **Why:** holding out a middle year can't test a level per year or recency weighting; forward is how
  the model is used.

### V2. The same days for every model

- **Chosen:** a day counts only if every model in the comparison was scored on it; GB only if all 13
  LDZs were; repaired days never.
- **Why:** otherwise scores differ by which days each model happened to cover.

### V3. A regime needs 90 training days

- **Chosen:** where a model's level and slope change on a date, a held-out year is scored only if each
  period between those dates has at least 90 training days.
- **Why:** SE's post-2022 level was once estimated from five odd days (RMSE 22 instead of 6).

### V4. Benchmarks: the official CWV, and National Gas's forecasts

- **Chosen:** the published CWV through the same regression (with a break where its definition
  changed); and National Gas's own day-ahead demand forecasts, on total demand.
- **Why:** the first isolates the weather input; the second is what the market sees.
- **Caveats:** ours used actual weather (small at day-ahead); theirs also forecasts DM. Like for like
  needs our model on the ensemble ([results, National Gas comparison](results.md#against-national-gass-day-ahead-forecasts)).

---

## Not used (yet)

### N1. Prices

TTF prices as an input: the price–demand link is weak and hard to separate from weather in five years.
A possible later experiment.

### N2. Daily min / max temperature

They help (−1.8% on top of P5), but ERA5's are the extremes of hourly values and the ensemble's come
from its own period extremes, which run colder / warmer — trained on one, run on the other, the model
would be off on the days it leans on. Revisit with a shared definition ([results, exp. 2](results.md#experiments-2-and-5-variables-and-the-gas-day-temperature)).

### N3. Precipitation

Built in the weather tables, not yet tested in the model.
