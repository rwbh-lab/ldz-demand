# Methodology

*Working document: what the model is, why it is built this way, and what is still open. Decisions are
recorded with their reasons and the evidence behind them; anything not yet tested is marked as such.*

Last updated: 13 October 2026.

---

## 1. Aim

Forecast daily gas demand in each of Great Britain's 13 Local Distribution Zones (LDZs) from the
weather, and turn ECMWF ensemble forecasts into probabilistic LDZ demand forecasts out to 15 days.

The industry standard is the **Composite Weather Variable (CWV)**: one weather number per LDZ and gas
day, built so that non-daily-metered (NDM) demand is a straight line in it. This project keeps the
idea and rebuilds the inputs:

- weather from a **grid** (ERA5 reanalysis, ECMWF ensemble forecasts) averaged over each LDZ and
  weighted to where gas is used, instead of one weather station per LDZ;
- the CWV's form **fitted to our own data**, with variants tested against each other rather than one
  method assumed best.

The aim is the best model we can build from free, public data — not a replica of the official one.

---

## 2. The official CWV

### 2.1 Definition

From National Gas, *Gas Demand Forecasting Methodology* (2016, Appendix 1) and Xoserve, *Composite
Weather Variable* (September 2026). The structure is unchanged between them:

    Et   = y · Et−1 + (1 − y) · ATt                                         effective temperature
    CWt  = I1 · Et + (1 − I1) · St − I2 · max(0, Wt − W0) · max(0, T0 − ATt) + S0 · SRt
    CWVt = V1 + q · (V2 − V1)        if CWt ≥ V2                             summer cut-off
         = V1 + q · (CWt − V1)       if V1 < CWt < V2                        transition
         = CWt                       if V0 ≤ CWt ≤ V1                        normal
         = CWt + I3 · (CWt − V0)     if CWt < V0                             cold-weather upturn

AT actual temperature, W wind speed (knots), SR solar radiation, S the pseudo seasonal normal
effective temperature (pseudo-SNET): a day-of-year profile derived from long-run weather and reshaped
to seasonal NDM demand.

### 2.2 What has changed since 2016

| | 2016 (National Gas) | Current (Xoserve, 2026) |
|---|---|---|
| Effective temperature weight `y` | fixed 0.5 | fitted per LDZ, 0.43–0.50 |
| Solar radiation | not used | `+ S0 · SR` (S0 0.47–0.96), plus a pseudo seasonal normal solar profile (pseudo-SNES) |
| Daily inputs | 2-hourly temperature, 4-hourly wind | 24 hourly observations, weighted |
| SW station | Filton | Yeovilton (NO solar from Durham; WM wind and solar from Coleshill) |
| Parameters | 2014 review, data 2004/05–2013/14 | 2024 review, NDM demand 2015/16–2022/23; **in force 1 Oct 2025 – 30 Sep 2030** |

Points from the current parameters: the seasonal profile carries 24–40% of CW (`I1` 0.60–0.76); the
wind-chill threshold `W0` is negative in 12 of 13 LDZs, so wind chill applies at almost any wind speed;
`T0` is 13–24 °C. The full specification (including the hourly weighting) is in the NDM Algorithms
Booklet on Xoserve's secured site.

### 2.3 What the official CWV is for

The CWV, its seasonal normal (SNCWV) and the pseudo-SNET are parts of a **settlement standard**: NDM
gas is allocated to shippers as `AQ/365 × ALP × (1 + DAF × (CWV − SNCWV))`. That use favours
stability (parameters fixed for 5 years), replicability (restated histories published to industry
parties), and agreed governance (the Demand Estimation Sub-Committee) — not the best possible
forecast. National Gas notes there is "no requirement" for forecasting to use the same CWV; it does
for efficiency. So the official CWV is the common standard, and a reasonable baseline, but not a
ceiling.

Two consequences:

- **Two targets matter to a trader:** physical demand, and the official forecast built on the official
  CWV (which is what the market reacts to). This project models physical demand, and is validated
  against the official forecast (§7).
- The published NDM demand is itself calculated from the CWV, so it is circular as a modelling target
  (§3).

### 2.4 What is and isn't public

Public: the formula, current parameters and stations (Xoserve slides); the actual and forecast CWV per
LDZ and day (National Gas data portal). Not public: the daily SNCWV and pseudo-SNET / pseudo-SNES
profiles, the restated CWV history on the 2025 formula (1960/61–2024/25), and the optimisation method
— all on UK Link Docs, Xoserve's secured site for industry parties (e.g. licensed shippers).

---

## 3. Target

**Total LDZ demand minus daily-metered (DM) demand**, both metered, converted to energy
(`kWh = mcm × 10⁶ × CV / 3.6`) and taken at D+6 close-out. It is the weather-sensitive part of
demand: NDM plus unidentified gas and LDZ shrinkage. Published NDM is not used as the target because
it is calculated from the CWV.

Two versions, to check results are robust to a data repair (`ldz_demand.data.ldz_energy`):

- **A (`target`)**: flagged days excluded — invalid totals, a missing non-NTS feed, totals far from
  the NTS offtakes.
- **B (`target_repaired`)**: as A, but days with SE's missing feed (Sep 2022 – Feb 2024) repaired as
  offtakes plus the usual input.

**Checked (October 2026): no step changes from sites changing metering class.** These would shift
the target with no change in weather. Comparing summer levels year by year, DM and the target mostly
move together (both fell in almost every LDZ from 2024 to 2025: lower demand generally), and the large
DM changes — NO halving, SO and WS — leave the target unchanged (large sites changing output or
closing). One odd day, SE on 4 July 2023 (both targets far below normal), is left to the model's
outlier handling.

---

## 4. Weather per LDZ

Built and compared on the *LDZ geography* and *LDZ weather* pages.

### 4.1 Which places belong to which LDZ

No official LDZ boundary file is public, so membership is derived and four methods are kept as
variants: local authority (town votes), Voronoi (the original method), hybrid, and **sampled**
(postcodes checked against the gas network operators' own checkers inside authorities on an LDZ
boundary). Checked against measured demand: sampled is closest (mean gap 0.50 percentage points of GB
gas use per LDZ).

**Finding:** with gas-use weighting, the four methods give LDZ temperatures within 0.01–0.05 °C of
each other day to day. The map method is settled; it does not drive the model.

### 4.2 How places inside an LDZ are weighted

Variants on the ERA5 0.25° grid: land area; gas use (DESNZ local-authority consumption); and the
official station (the grid point at the CWV station).

**Finding:** weighting matters (area vs gas use 0.1–0.45 °C day to day), and the official stations
differ most from gas-weighted LDZ temperature: NE 0.69 °C (its station is Nottingham Watnall, in EM),
WN 0.52, EA and SE 0.46 (Heathrow). Whether that improves the demand fit is the first model test
(§6.1).

**Finding: the station differences are seasonal** (LDZ weather page §4). On average by month, the
station minus our gas-weighted temperature swings by up to ~0.8 °C through the year: St Athan (WS)
reads up to +0.85 °C warm in November and +0.06 °C in May — a coastal station, warm when the sea is
warmer than the inland towns and valleys where WS's gas is used; Southampton (SO) the same, weaker
(+0.45 to +0.09); Heathrow reads −0.49 °C against SE in October and +0.25 °C in June; Watnall (NE)
+0.3 in winter to +1.3 °C in summer. The same gaps appear in the ensemble forecasts (WS ~+0.9 °C at
every lead day in October 2026 runs), so they come from the station sites, not the forecast.

### 4.3 Variables and the gas day

Gas day 05:00–05:00 UK time. Per LDZ and gas day: mean temperature, wind speed and solar radiation;
lowest and highest hourly temperature; total precipitation. Kept hourly too (`weather_ldz_hourly`) so
the way a day is averaged can itself be tested (§5.4). Forecasts use the same cell weights, so forecast
and reanalysis weather mean the same thing.

---

## 5. Model design

### 5.1 Starting point

The official form (§2.1) is the baseline structure, refitted per LDZ for each weather variant. Its
parameters were fitted on 2015/16–2022/23; ours on what we have — demand from October 2021, about five
gas years. That changes what can be estimated, and the design below follows from it.

### 5.2 What we keep, change and add

| | Decision | Why |
|---|---|---|
| Effective temperature | keep, `y` fitted per LDZ | thermal inertia of buildings; well identified in five years |
| Wind chill | keep, form refitted | well identified on cold, windy days |
| Solar radiation | **test** | in the official form since 2020; added to our weather data, so its value is an experiment |
| Summer cut-off, transition | keep | demand flattens when heating is off |
| Cold-weather upturn | keep simple (§5.5) | few cold days in five years |
| Seasonal profile (pseudo-SNET) | **replace** (§5.3) | not public, and can't be estimated well from five years |
| Day of week, holidays | add | standard demand calendar effects |
| Level and sensitivity over time | add (§5.3) | behaviour changed after 2022 |

### 5.3 Seasonal behaviour and the 2022 change

The official CW takes 24–40% from a fixed seasonal profile, which mostly stands in for behaviour —
heating switched on in autumn after a run of cold days, left on into spring. We can't use theirs
(§2.4), and estimating a calendar shape from five years risks fitting the particular years we have.

**Provisional design:**

1. **A slow "heating-season" temperature** — a second effective temperature with a long memory (1–3
   weeks), alongside the fast one. One or two parameters, physically interpretable, and it follows
   each year's actual weather rather than the date; it gives the autumn / spring asymmetry naturally.
2. **Level and weather sensitivity allowed to change over time** — per gas year, a break in autumn
   2022, or slowly adapting coefficients — for the change in behaviour after the 2022 price shock
   (demand reduction) and any since (prices high again in 2026).

**Tested alternative:** a smooth day-of-year shape (one or two sine / cosine pairs), **one shape
shared by all LDZs** with only its size fitted per LDZ — roughly a fitted, low-detail pseudo-SNET.
Pooling gives about 13 times the data for the shape. Used only if it beats the design above on held-out
years.

Not in the core model: prices (TTF) as an input. The price–demand link is weak and hard to separate
from weather in five years; a possible later experiment.

Partly in our favour: the official parameters reflect mostly pre-2022 behaviour, while our five years
are mostly after it — more current, though with the 2022 break inside them.

**Hypothesis: part of the official seasonal profile corrects for where the stations are.** A station
bias that changes through the year (§4.2) can't be absorbed by a constant; in the official CWV the
seasonal profile is the term that can. If so, a gas-weighted LDZ temperature, without the siting bias,
should need a smaller seasonal term — helpful with five years of data. Tested in §6 (experiment 3),
most clearly in WS, SO and SE.

### 5.4 Averaging the gas day

The official CWV weights 24 hourly observations (weights not published). Variants to test: flat
(time-weighted) mean; weighting the morning and evening heating peaks; minimum / maximum, or a
day / night split. Forecast steps are 3-hourly to day 6 and 6-hourly after, so any method must also
work at that resolution; its cost is measurable by applying the same sampling to hourly ERA5.

### 5.5 The cold end

The cold-weather upturn needs cold days, and five years have few (December 2022, January 2026). The
National Gas portal keeps a rolling five years, so no earlier demand is available. Options, to be
compared on those cold spells: a simple linear or single-kink upturn; constraining it towards the
published parameters. Results on the coldest days will be reported separately and treated with
caution.

---

## 6. Experiments

Each is a variant fitted the same way and judged on held-out years (§7):

1. **Weather input:** official CWV (benchmark; with a break at 1 Oct 2025, when its definition
   changed); ERA5 at the official station; sampled × gas use; sampled × area; other map methods.
   The station-vs-gas-weighted comparison separates "one point vs the whole LDZ" from "reanalysis vs
   station observations".
2. **Variables:** with / without solar radiation; with / without temperature extremes.
3. **Seasonal term:** none; slow heating-season temperature; pooled calendar shape. Fitted for both the
   station and the gas-weighted input: if the station needs the larger seasonal term (WS, SO, SE in
   particular), the seasonal profile is partly correcting the station siting (§5.3).
4. **Change over time:** fixed; per gas year; break in 2022; adapting.
5. **Gas-day averaging:** flat; heating-peak weighted; extremes.
6. **Target:** A and B.

---

Results, as they come in: [results.md](results.md).

## 7. Validation

- **Held out by gas year:** fit on all other years, score the held-out one; repeat for each.
- **Forward, for change over time** (experiment 4): each year predicted from the years before it only
  — a level per gas year can't be estimated for a held-out middle year.
- **Regimes:** where the level and slope change on a date, a held-out year is scored only if each
  period between those dates it contains has at least 90 training days.
- **Scores:** RMSE and MAPE per LDZ; separately for winter and for the coldest days.
- **Against National Gas's own forecasts** (`ng_forecast_daily`, every issue since October 2021),
  not CWV against CWV — the official CWV changed definition in October 2025, but each forecast used
  whatever was in force, so the comparison is fair throughout. Like for like: their total LDZ demand
  forecast minus actual DM, against our forecast of total minus DM, matched by issue time (their
  day-ahead issues are ~13:00–24:00 on D−1; ours come from the 00z ensemble, published ~09:30).
- **Two levels:** model skill with actual weather (our model on ERA5); forecast skill with forecast
  weather (our model on the ensemble), by lead day.

---

## 8. Forecasting

ECMWF ensemble, 50 members, 15 days, 00z run, archived daily (user guide §5.3). Each member through
the fitted model gives a demand distribution per LDZ and gas day. Still to design:

- **Effective temperature at the start of a forecast** needs the days before the run; ERA5 runs ~5
  days behind, so those days come from earlier forecast runs' day-0 values.
- **Forecast vs reanalysis bias** by lead time and season, corrected before the model.
- **Scoring** probabilistic forecasts (CRPS) once the archive is long enough; backfilling past winters
  from ECMWF's cloud mirror is planned.

---

## 9. Caveats

- **Five years of demand.** Seasonal behaviour, the post-2022 change and the cold end can't be
  separated with certainty; findings on them are provisional.
- **No official LDZ boundary.** Membership is derived; its effect on LDZ weather is shown to be small
  (§4.1).
- **Reanalysis, not observations.** ERA5 is a model of the weather; at a station it can differ from
  the station's own readings — tested directly (§6.1).
- **National Gas's seasonal profile** comes from decades of weather data that isn't public, so we
  model the behaviour it stands in for instead.
- **The target** includes unidentified gas and shrinkage, and moves if sites change metering class.

---

## Sources

- National Gas, *Gas Demand Forecasting Methodology* (2016).
- Xoserve, [*Composite Weather Variable*](https://xoserve.com/media/4uvo4hpj/composite-weather-variable.pdf) (September 2026).
- Xoserve, [*Seasonal Normal Composite Weather Variable*](https://www.xoserve.com/media/qfehz3t3/seasonal-normal-composite-weather-variable_sept26.pdf) (September 2026).
- Xoserve, [*Seasonal Normal Review 2025*](https://www.gasgovernance.co.uk/sites/default/files/related-files/2025-10/Seasonal%20Normal%20Review%202025.pdf) (October 2025).
- Joint Office, [*UNC NDM Demand Estimation Methodology* v1.4](https://www.gasgovernance.co.uk/sites/default/files/related-files/2023-10/Demand%20Estimation%20UNC%20Related%20Document%20v1.4.pdf) (2019).
