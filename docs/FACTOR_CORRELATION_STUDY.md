# Factor Correlation Study — Confluence Factors vs Forward Returns

Study date: 2026-07-09. Status: **RESEARCH ONLY — COMPLETE. Result: NULL
(no candidate rule met the pre-registered criteria; the holdout was never
run, by design).**

> **RESEARCH — NO TRADING IMPACT.** This study makes no trades, changes no
> strategy module, and its results gate nothing. Data is historical
> Hyperliquid candles (frozen snapshots, same 5,000-bar retention as every
> backtest in this repo); all statistics are descriptive; no
> slippage/funding/cost model applies because nothing is traded. A null
> result is a valid and expected outcome. Any future weighted-confluence
> strategy ("Track 4") would be a separate build, reviewed the normal way,
> only if these findings justify it.

## 1. Question & scope

Every track built so far (trend system, Track 2 counter-trend) uses hard
boolean gates — bias must be exactly BULLISH, Fisher must cross a fixed
threshold. Real confluence trading is weighted and odds-based. Fitting
weights to the ~9–27 trade outcomes per track would be curve-fitting: a
model with several tunable weights has more freedom than a sample that
small can constrain. This study instead uses the full ~5,000-candle 1H and
4H histories (thousands of bars, not tens of trades) to measure which of
four stated confluence factors actually correlate with forward price
movement, **before** any weighted rule is proposed.

**This study is NOT:** a tradeable module, a Track 4 implementation, an
optimizer search, or anything wired into Track 2/Track 3/the live forward
test. It is fully independent of all of those.

## 2. Pre-registration (frozen before any results were computed)

The constants block at the top of `scripts/factor_correlation_study.py` is
the operative pre-registration; this section restates it. Pre-registration
commit: `0f21aac` (script + this section committed before `--phase explore`
first ran).

### 2.1 Factor definitions (per closed bar i, per timeframe series)

All factors reuse the repo's live indicator code — no reimplementation.
Unified row start i ≥ 120 (production `WARMUP_BIAS_BARS`), which covers
every factor's warm-up. Structure and Ichimoku are computed on a fresh
trailing 300-bar slice per bar (`LOOKBACK_BARS`, matching the backtest
harness) because fractal swings only confirm 2 bars after the fact —
per-bar slicing is what makes F1 non-repainting. Fisher and ATR are causal
recursive filters and are precomputed full-series.

- **F1 — candle close position vs structure** = `(close − nearest_support)
  / (nearest_resistance − nearest_support)` where the S/R levels come from
  `compute_bias(window, fractal_width=2, sr_lookback=20)` on the **same
  timeframe's** trailing 300-bar slice, and nearest support/resistance are
  the closest levels strictly below/above the close
  (`strategy/signals.py:_nearest_support/_nearest_resistance`). Undefined
  (row excluded for F1, counted) when either side is missing — i.e. at
  breakouts beyond known structure — or when resistance ≤ support.
  0 = at support, 1 = at resistance. **Deviation from production noted:**
  the live system pairs 4H structure with 1H triggers; this study is
  deliberately self-contained per timeframe (see §10; the production
  pairing is named future work in §12).
- **F2 — Fisher vs R-line** = `fisher[i] − trigger[i]` where
  `(fisher, trigger) = fisher_transform(candles, period=10)`
  (`strategy/trigger_1h.py`) and `trigger[i] = fisher[i−1]` is the
  1-bar-delayed signal line (the "R-line"). Signed continuous gap — the
  factor is Fisher's position relative to its trigger line, not the cross
  event used elsewhere.
- **F3 — Ichimoku leading cloud distance** = signed, ATR-normalized:
  `(close − cloud_top)/ATR14` if close above the cloud,
  `(close − cloud_bottom)/ATR14` if below (negative), `0.0` inside. Cloud
  edges from `ichimoku_components(window, variant="standard")` (9/26/52,
  displaced 26 bars — chart-standard and causal). Undefined when cloud or
  ATR is unavailable.
- **F4 — Fisher level** = `fisher[i]` raw, the extended/neutral value used
  across every other track. ±2.0 is the repo's established "extended"
  threshold.

Warm-up/sentinel handling: exclusion is **by index** (Fisher i ≥ 9, F2
i ≥ 10, ATR i ≥ 14, Ichimoku ≥ 78 bars of history), never by value == 0.0.

### 2.2 Target variable

Forward log return `ln(close[i+N] / close[i])`, fixed before any results
were computed. Horizons: **N ∈ {4, 12} on 1H; N ∈ {2, 6} on 4H** — four
(tf, N) panels. Grounding (queried from prior backtests' `backtest_trades`
before this study ran, not tuned afterward): 1H-trigger trades held median
2 / mean 4.8 bars; 4H-trigger median 5.5 / mean 6.2 bars. The chosen
horizons bracket those actual hold times.

### 2.3 Data split

Chronological 70/30: `split_index = floor(0.70 · bar_count)` computed at
fetch time and **stored inside each frozen snapshot file** — the boundary
cannot drift as Hyperliquid's rolling 5,000-bar retention advances.

**N-bar purge:** exploration rows are `i ≤ split_index − 1 − N` so no
exploration target reaches into the holdout. Holdout rows are
`split_index ≤ i ≤ n − 1 − N`. Holdout **factors** legitimately use
pre-split history (they are backward-looking); only targets are quarantined.
The exploration phase hard-asserts it never reads a row whose target
crosses the boundary.

### 2.4 Thresholds & cell family

Eight base conditions at pre-registered round-number thresholds:

| Condition | Definition |
|---|---|
| F1_near_support | F1 ≤ 0.25 |
| F1_near_resistance | F1 ≥ 0.75 |
| F2_fisher_above_rline | F2 > 0 |
| F2_fisher_below_rline | F2 < 0 |
| F3_above_cloud | F3 > 0 |
| F3_below_cloud | F3 < 0 |
| F4_extended_low | F4 ≤ −2.0 |
| F4_extended_high | F4 ≥ +2.0 |

Cell family per panel: 8 singles + 24 cross-factor 2-ANDs + 32 cross-factor
3-ANDs = **M = 64** (same-factor combos excluded as contradictory or
redundant; count asserted in code). Each cell reports its **signed**
conditional mean — no separate long/short duplication, direction is read
from the sign. A row with an undefined constituent factor cannot fire a
cell. **All 64 cells are reported in every panel, including nulls
(Appendix A).** Eligibility floor for candidate selection: exploration
n ≥ 30 and projected holdout firings (fire-rate × holdout rows) ≥ 20 —
smaller cells are reported but ineligible.

### 2.5 Candidate selection & holdout criteria (verbatim from the script)

Mechanical selection (no post-hoc judgment; user-selected one-pass mode):

> highest |t_NW| among cells with n ≥ 30 and projected holdout firings
> ≥ 20, requiring |t_NW| > panel shift-calibration 95th-pct bar AND
> same-sign mean at the sibling horizon of the same timeframe

If no cell qualifies: **no candidate — the holdout never runs** and the
study reports a null result.

Holdout support criteria (single one-shot test, write-once output file):

> same sign as exploration AND |t_NW| ≥ 2.0 on holdout

## 3. Data

| | 1H | 4H |
|---|---|---|
| Snapshot file | `research/data/BTC_1h_snapshot.json` | `research/data/BTC_4h_snapshot.json` |
| Fetched at (UTC) | 2026-07-09 | 2026-07-09 |
| Bars (closed, gap-free) | 5,002 | 5,000 |
| Window (close times) | 2025-12-12 18:59 → 2026-07-09 03:59 | 2024-03-27 23:59 → 2026-07-09 03:59 |
| Split index / last exploration close | 3501 / 2026-05-07 15:59 | 3500 / 2025-11-01 07:59 |

Per-factor availability on the exploration split (F2/F3/F4 are defined on
every row; F1 is undefined at breakouts beyond known structure):

| Panel | Rows | F1 defined | F1 missing (rate) |
|---|---|---|---|
| 1H N=4 | 3,377 | 3,024 | 353 (10.5%) |
| 1H N=12 | 3,369 | 3,016 | 353 (10.5%) |
| 4H N=2 | 3,378 | 3,056 | 322 (9.5%) |
| 4H N=6 | 3,374 | 3,052 | 322 (9.5%) |

Well under the 40% interpretability flag — F1's defined subset is
representative enough to analyze.

## 4. Method

- **Correlations:** Spearman rank correlation (average-rank ties) is
  primary — forward returns are heavy-tailed and Pearson is
  outlier-dominated; Pearson is reported as a magnitude check. These are
  descriptive: with overlapping N-bar targets the effective sample is
  roughly n/N, so a rule-of-thumb standard error is 1/√(n/N). No
  correlation is treated as inference-grade.
- **Quintile tables** per factor (breakpoints computed on exploration rows
  only): the interpretability layer between a raw ρ and a threshold rule —
  a monotone quintile spread is what would justify a rule, not a bare ρ.
- **Cell statistics:** every cell's conditional mean carries a
  **Newey–West (Bartlett) t-statistic with lag = N−1**, computed on the
  full row-ordered series with non-fired rows contributing zero — the
  correct treatment of irregular firings under serially correlated,
  overlapping targets. At lag 0 this reduces exactly to the classical SE
  (self-tested). These are serial-correlation-adjusted descriptive
  t-stats, not p-values.
- **Multiple comparisons:** M = 64 cells per panel means ~3 cells clearing
  |t| > 2 by chance under the global null. Two devices are reported per
  panel: (a) the observed count of |t| > 2 cells next to that expectation;
  (b) a **circular-shift max-|t| calibration** — the 8 base condition masks
  are rotated together by 200 seeded offsets, all 64 cells recomputed per
  shift, and the 95th percentile of the per-shift max |t_NW| becomes the
  panel's empirical "surprise bar" (jointly accounting for multiplicity,
  autocorrelation, and inter-cell correlation). A Bonferroni reference is
  |t| ≈ 3.2 (0.05/64, two-sided). Cells are never filtered by any of this —
  everything is reported.
- **Robustness (final candidate only):** N-phase non-overlapping
  subsampling — fired rows split by bar-phase mod N give N disjoint
  subsamples whose targets share no bars; naive t per phase.
- **Minimum detectable effect (read before interpreting a null):** the 1H
  holdout has ~1,450 usable rows; at N=12 that is n_eff ≈ 120
  unconditional, and a cell firing 10% of the time has perhaps 40–80
  effectively independent observations. With 12-bar BTC volatility ≈ 2%,
  the smallest conditional edge detectable at t = 2 is roughly 0.5–0.7%
  per window — a *large* edge. A null here means "no economically large
  effect detected on this window," not "no effect exists."

## 5. Exploration results — 1H

Unconditional mean forward return: −0.007% (N=4), −0.023% (N=12) — the
exploration window is drift-flat.

### 5.1 Per-factor correlations vs forward return

| Factor | N=4 ρ_S | N=4 ρ_P | N=12 ρ_S | N=12 ρ_P | n_eff (N=4/12) |
|---|---|---|---|---|---|
| F1 range position | −0.016 | +0.006 | −0.002 | +0.008 | 756 / 251 |
| F2 R-line gap | −0.039 | −0.008 | −0.038 | −0.022 | 844 / 281 |
| F3 cloud distance | −0.047 | −0.023 | −0.044 | −0.037 | 844 / 281 |
| F4 Fisher level | −0.047 | −0.003 | +0.009 | +0.021 | 844 / 281 |

With rule-of-thumb SE ≈ 1/√n_eff ≈ 0.034–0.063, **no correlation is even
2 SE from zero.** The largest (F3/F4 at N=4, ρ_S ≈ −0.047) is ~1.4 SE.
F3's inside-cloud point mass is 16.5% of rows; excluding it moves F3's ρ_S
to −0.053 (N=4) / −0.063 (N=12) — same conclusion. The weakly negative
signs on F2/F3/F4 point mean-reversion-ward but are not distinguishable
from noise.

### 5.2 Quintile tables (mean forward return by exploration quintile)

| Factor, N | Q1 | Q2 | Q3 | Q4 | Q5 | Monotone? |
|---|---|---|---|---|---|---|
| F1, N=4 | +0.00047 | +0.00004 | −0.00020 | −0.00006 | +0.00070 | no (U-shape) |
| F2, N=4 | −0.00035 | +0.00015 | +0.00021 | +0.00064 | −0.00103 | no (breaks at Q5) |
| F3, N=4 | −0.00026 | +0.00028 | +0.00142 | +0.00034 | −0.00123 | no (hump) |
| F4, N=4 | −0.00019 | −0.00053 | +0.00093 | −0.00014 | −0.00044 | no |
| F1, N=12 | +0.00041 | −0.00018 | +0.00027 | +0.00065 | +0.00044 | no |
| F2, N=12 | +0.00046 | −0.00064 | +0.00031 | +0.00082 | −0.00208 | no |
| F3, N=12 | −0.00043 | −0.00079 | +0.00426 | +0.00309 | −0.00323 | no (inside-cloud hump) |
| F4, N=12 | −0.00234 | −0.00032 | +0.00040 | +0.00204 | −0.00092 | no |

No factor shows the monotone gradient that would justify a threshold rule.
The recurring shape is a middle-quintile hump (returns concentrated when
the factor is *neutral*), most visible in F3 at N=12 — the opposite of a
usable extreme-value signal.

### 5.3 Combination cells

| Panel | |t_NW|>2 cells (n≥30) | Expected by chance | Calibration bar (p95 max\|t\|) | Shift-null median max\|t\| | Observed max \|t_NW\| |
|---|---|---|---|---|---|
| 1H N=4 | 3 | ~2.9 | 3.64 | 2.48 | 2.59 |
| 1H N=12 | 2 | ~2.9 | 3.54 | 2.28 | 2.09 |

The observed exceedance counts match chance, and the observed max |t| in
each panel sits near the *median* of the shift-null max-|t| distribution —
i.e. the best-looking cell is exactly as good as the best-looking cell in
shuffled data. Top cells for the record (full tables in Appendix A):

- N=4 #1: `F1_near_support + F2_fisher_below_rline + F4_extended_low`
  (washed-out dip near support) n=157, mean +0.24%, hit 0.68, t_NW +2.59.
- N=4 #2: `F3_above_cloud + F4_extended_high` (extended above cloud)
  n=487, mean −0.15%, hit 0.41, t_NW −2.51.
- N=12 #1: `F1_near_support + F2_fisher_above_rline + F3_above_cloud`
  n=57, mean +0.39%, hit 0.61, t_NW +2.09.

None clears its panel's calibration bar (3.64 / 3.54).

## 6. Exploration results — 4H

Unconditional mean forward return: +0.032% (N=2), +0.101% (N=6) — the
2024–2025 exploration window carries positive drift; conditional means
must be read against that baseline.

### 6.1 Per-factor correlations vs forward return

| Factor | N=2 ρ_S | N=2 ρ_P | N=6 ρ_S | N=6 ρ_P | n_eff (N=2/6) |
|---|---|---|---|---|---|
| F1 range position | −0.023 | −0.003 | −0.021 | −0.004 | 1528 / 509 |
| F2 R-line gap | −0.039 | −0.040 | −0.001 | −0.018 | 1689 / 562 |
| F3 cloud distance | −0.034 | −0.018 | −0.041 | −0.034 | 1689 / 562 |
| F4 Fisher level | −0.005 | +0.030 | +0.041 | +0.070 | 1689 / 562 |

Same picture: nothing reaches 2 rough SEs. The most interesting number in
the whole study is F4 at N=6 (ρ_P +0.070, quintiles below) — a weak
trend-following tilt (high Fisher → higher forward return), but at ~1 SE
on n_eff it is indistinguishable from the window's drift.

### 6.2 Quintile tables

| Factor, N | Q1 | Q2 | Q3 | Q4 | Q5 | Monotone? |
|---|---|---|---|---|---|---|
| F1, N=2 | −0.00016 | +0.00136 | −0.00017 | −0.00017 | +0.00020 | no |
| F2, N=2 | +0.00093 | +0.00024 | +0.00048 | +0.00064 | −0.00068 | no |
| F3, N=2 | +0.00123 | −0.00026 | +0.00033 | +0.00028 | +0.00034 | no |
| F4, N=2 | −0.00023 | +0.00071 | −0.00057 | +0.00073 | +0.00096 | no |
| F1, N=6 | −0.00016 | +0.00234 | +0.00078 | −0.00049 | +0.00054 | no |
| F2, N=6 | +0.00101 | +0.00104 | +0.00064 | +0.00302 | −0.00069 | no |
| F3, N=6 | +0.00363 | −0.00050 | +0.00044 | +0.00158 | +0.00039 | no |
| F4, N=6 | −0.00134 | +0.00076 | +0.00061 | +0.00225 | +0.00274 | roughly (weak) |

F4 at N=6 is the only near-monotone row in the study (Q1 −0.13% → Q5
+0.27%), consistent with its positive ρ — noted for the record, ~1 SE.

### 6.3 Combination cells

| Panel | |t_NW|>2 cells (n≥30) | Expected by chance | Calibration bar (p95 max\|t\|) | Shift-null median max\|t\| | Observed max \|t_NW\| |
|---|---|---|---|---|---|
| 4H N=2 | 0 | ~2.9 | 3.73 | 2.68 | 1.98 |
| 4H N=6 | 1 | ~2.9 | 3.76 | 2.75 | 2.00 |

Both panels are *below* chance expectation, and both observed maxima sit
below the shift-null median. Top cells for the record: 4H N=6 #1
`F1_near_resistance + F2_fisher_below_rline + F4_extended_high` n=105,
mean +0.48%, t_NW +2.00; #2 `F1_near_resistance + F3_below_cloud` n=168,
mean +0.49%, t_NW +1.98. Neither approaches the 3.76 bar.

## 7. Candidate rule

**No candidate met the pre-registered criteria.** Applied mechanically
across all four panels: no cell with n ≥ 30 and projected holdout firings
≥ 20 exceeded its panel's shift-calibration bar (best shortfall: |t| 2.59
vs bar 3.64 on 1H N=4). Per §2.5, the study ends here as a null result.

## 8. Holdout result

**Not run — by design.** The pre-registered protocol reserves the holdout
for exactly one qualified candidate; with none, the 30% holdout
(1H: 2026-05-07 → 2026-07-09; 4H: 2025-11-01 → 2026-07-09) remains
untouched and uncontaminated. It stays valid for a future candidate from a
*different* factor set or definition round, provided that candidate is
specified without ever analyzing these holdout rows.

## 9. Findings (honest read)

1. **Null result, cleanly obtained.** None of the four factors — S/R range
   position, Fisher-vs-R-line gap, Ichimoku cloud distance, raw Fisher —
   shows exploitable correlation with 4–12-bar (1H) or 2–6-bar (4H)
   forward returns on this data, individually or in any of the 256
   pre-registered boolean combinations. Every exceedance count is at or
   below chance; every panel's best cell is statistically typical of
   shuffled data.
2. **The multiplicity guard did its job.** The 1H N=4 top cell (+2.59
   t_NW, hit rate 0.68, a plausible-sounding "buy the washed-out dip near
   support" story) is precisely the kind of cell that gets promoted to a
   strategy by unguarded exploration. The calibration bar (3.64) says a
   cell that good or better appears in ~half of shuffled datasets. Without
   pre-registration this study would have "found" something.
3. **What weak structure exists points two ways at once.** 1H extremes
   lean mean-reversion (extended-above-cloud → negative); 4H N=6 Fisher
   leans trend-following (the only near-monotone quintile row, ρ_P +0.070,
   ~1 SE, confounded with the window's +0.1%/6-bar drift). Neither
   survives any significance device; together they mostly illustrate why
   neither should be trusted without out-of-sample confirmation.
4. **Returns concentrate when factors are *neutral*.** The recurring
   quintile shape is a middle hump (e.g. F3 N=12: Q3/Q4 positive, both
   tails negative) — the opposite of what a weighted-extremes confluence
   rule assumes. If anything in this study motivates a follow-up
   hypothesis, it is this, not any extreme-value cell.
5. **Bounded claim.** Per the MDE statement (§4), this rules out
   economically *large* edges (≳0.5%/window conditional) for these
   factors/definitions/horizons on this window. It does not rule out small
   edges, other definitions (e.g. F1 from 4H structure on 1H bars), other
   regimes, or interaction with the bias gate the live system actually
   trades through.
6. **Recommendation: do not build Track 4 from these four factors at
   these thresholds.** The statistical grounding the build plan asked for
   does not exist in this data. The factor-computation and study harness
   are reusable for a second round with different definitions if desired.

## 10. Limitations & threats to validity

- **Overlapping targets / effective sample:** all t-stats are NW-adjusted,
  but n_eff ≈ n/N still bounds what is knowable; see the MDE statement in §4.
- **Single-regime 1H window:** ~208 days of 1H data is one market regime;
  the 4H series (~2.3 years) is the only multi-regime view.
- **Multiplicity:** 64 cells × 4 panels; the calibration bar and exceedance
  counts are mitigations, not cures. Only a holdout test would have been
  inference-grade, and none was warranted.
- **Self-contained structure (F1):** deviates from the production
  4H-structure-for-1H pairing by design (clean per-TF comparability); the
  production pairing is untested here.
- **Economic vs statistical significance:** no cost model — even a
  supported cell would have been a statement about raw forward returns,
  not net-of-fees strategy performance.
- **Snapshot specificity:** results are conditional on this exact frozen
  window; Hyperliquid retention makes the 1H window unrepeatable later.

## 11. Reproduce

```powershell
python scripts/factor_correlation_study.py --phase selftest
python scripts/factor_correlation_study.py --phase explore --tf both   # from the committed snapshots
# --phase fetch would pull a NEW window (= a new study, not a reproduction)
# --phase holdout exits: CANDIDATE_RULE is None (no candidate qualified)
```

Frozen inputs and full machine-readable results are committed under
`research/data/` and `research/output/` (`explore_1h.json`,
`explore_4h.json` — every cell, quintile, and calibration number in this
doc is derived from those files).

## 12. Open items / future work

1. F1 from 4H structure for 1H bars (the production bias/trigger pairing)
   — the one named variant this round deliberately did not test.
2. The "neutral-factor hump" observation (§9.4) as a hypothesis of its own
   — would need a fresh pre-registration; the current holdout remains
   uncontaminated and could serve it.
3. Alternative targets (ATR-normalized returns, max-favorable-excursion)
   — out of scope round 1 by pre-registration.
4. Track 4 (weighted confluence) is **not** justified by this study.

## Appendix A: full 64-cell tables (all four panels, nulls included)

Cells sorted by |t_NW| descending within each panel (enumeration order is
immaterial; every cell is shown). `n` = exploration firings, `fire%` =
share of panel rows, `mean` = conditional mean forward log return, `hit` =
fraction of firings with positive forward return, `t_NW` = Newey–West
t-stat (lag N−1). Machine-readable copies: `research/output/explore_*.json`.

### A.1 Panel 1H N=4 (rows 3,377; calibration bar 3.64)

| # | conditions | n | fire% | mean | hit | t_NW |
|---|---|---|---|---|---|---|
| 1 | F1_near_support + F2_fisher_below_rline + F4_extended_low | 157 | 4.6 | +0.00243 | 0.68 | +2.59 |
| 2 | F3_above_cloud + F4_extended_high | 487 | 14.4 | -0.00152 | 0.41 | -2.51 |
| 3 | F2_fisher_below_rline + F3_above_cloud + F4_extended_high | 199 | 5.9 | -0.00198 | 0.41 | -2.24 |
| 4 | F2_fisher_above_rline + F3_below_cloud + F4_extended_high | 94 | 2.8 | +0.00374 | 0.59 | +1.81 |
| 5 | F3_below_cloud + F4_extended_high | 145 | 4.3 | +0.00300 | 0.57 | +1.79 |
| 6 | F1_near_support + F2_fisher_above_rline + F4_extended_low | 79 | 2.3 | -0.00257 | 0.48 | -1.71 |
| 7 | F2_fisher_above_rline + F3_below_cloud + F4_extended_low | 169 | 5.0 | -0.00210 | 0.49 | -1.65 |
| 8 | F2_fisher_above_rline + F3_above_cloud + F4_extended_high | 288 | 8.5 | -0.00121 | 0.41 | -1.63 |
| 9 | F1_near_resistance + F2_fisher_below_rline + F3_above_cloud | 194 | 5.7 | -0.00133 | 0.44 | -1.62 |
| 10 | F1_near_support + F3_above_cloud + F4_extended_high | 18 | 0.5 | -0.00291 | 0.39 | -1.61 |
| 11 | F2_fisher_below_rline + F4_extended_high | 300 | 8.9 | -0.00112 | 0.45 | -1.57 |
| 12 | F1_near_resistance + F2_fisher_below_rline + F3_below_cloud | 57 | 1.7 | +0.00273 | 0.65 | +1.46 |
| 13 | F2_fisher_above_rline + F4_extended_low | 280 | 8.3 | -0.00133 | 0.46 | -1.42 |
| 14 | F1_near_support + F3_above_cloud + F4_extended_low | 44 | 1.3 | +0.00150 | 0.59 | +1.33 |
| 15 | F2_fisher_below_rline + F3_above_cloud | 717 | 21.2 | -0.00059 | 0.49 | -1.26 |
| 16 | F1_near_support + F2_fisher_below_rline + F3_below_cloud | 260 | 7.7 | +0.00091 | 0.58 | +1.16 |
| 17 | F1_near_support + F2_fisher_above_rline + F3_above_cloud | 57 | 1.7 | +0.00145 | 0.51 | +1.14 |
| 18 | F1_near_resistance + F2_fisher_above_rline + F3_above_cloud | 267 | 7.9 | +0.00086 | 0.49 | +1.08 |
| 19 | F1_near_resistance + F3_above_cloud + F4_extended_high | 179 | 5.3 | -0.00103 | 0.40 | -1.05 |
| 20 | F1_near_support + F3_below_cloud + F4_extended_high | 31 | 0.9 | +0.00184 | 0.48 | +0.93 |
| 21 | F1_near_resistance | 743 | 22.0 | +0.00044 | 0.51 | +0.89 |
| 22 | F2_fisher_below_rline + F4_extended_low | 435 | 12.9 | +0.00065 | 0.61 | +0.88 |
| 23 | F1_near_resistance + F2_fisher_above_rline | 426 | 12.6 | +0.00051 | 0.50 | +0.87 |
| 24 | F1_near_support + F2_fisher_below_rline | 442 | 13.1 | +0.00047 | 0.55 | +0.85 |
| 25 | F1_near_support + F4_extended_low | 236 | 7.0 | +0.00075 | 0.61 | +0.83 |
| 26 | F2_fisher_below_rline + F3_below_cloud + F4_extended_high | 51 | 1.5 | +0.00163 | 0.55 | +0.80 |
| 27 | F3_above_cloud + F4_extended_low | 173 | 5.1 | +0.00064 | 0.51 | +0.77 |
| 28 | F1_near_support + F2_fisher_below_rline + F4_extended_high | 33 | 1.0 | -0.00148 | 0.39 | -0.76 |
| 29 | F3_above_cloud | 1485 | 44.0 | -0.00028 | 0.48 | -0.75 |
| 30 | F4_extended_high | 741 | 21.9 | -0.00042 | 0.46 | -0.75 |
| 31 | F2_fisher_below_rline + F3_above_cloud + F4_extended_low | 102 | 3.0 | +0.00068 | 0.57 | +0.74 |
| 32 | F1_near_support + F2_fisher_above_rline + F3_below_cloud | 167 | 4.9 | -0.00064 | 0.49 | -0.68 |
| 33 | F3_below_cloud + F4_extended_low | 439 | 13.0 | -0.00063 | 0.57 | -0.66 |
| 34 | F1_near_resistance + F3_above_cloud + F4_extended_low | 43 | 1.3 | -0.00100 | 0.47 | -0.63 |
| 35 | F1_near_support + F3_below_cloud + F4_extended_low | 158 | 4.7 | +0.00071 | 0.63 | +0.59 |
| 36 | F1_near_resistance + F3_below_cloud | 158 | 4.7 | +0.00067 | 0.57 | +0.59 |
| 37 | F1_near_resistance + F3_below_cloud + F4_extended_high | 31 | 0.9 | +0.00160 | 0.71 | +0.55 |
| 38 | F1_near_support + F3_above_cloud | 165 | 4.9 | +0.00036 | 0.50 | +0.53 |
| 39 | F1_near_resistance + F2_fisher_below_rline + F4_extended_high | 87 | 2.6 | -0.00059 | 0.45 | -0.51 |
| 40 | F1_near_resistance + F2_fisher_below_rline + F4_extended_low | 54 | 1.6 | +0.00073 | 0.61 | +0.50 |
| 41 | F1_near_resistance + F4_extended_high | 245 | 7.3 | -0.00039 | 0.45 | -0.47 |
| 42 | F1_near_support + F3_below_cloud | 427 | 12.6 | +0.00030 | 0.54 | +0.47 |
| 43 | F1_near_resistance + F2_fisher_below_rline | 317 | 9.4 | +0.00035 | 0.51 | +0.46 |
| 44 | F1_near_resistance + F4_extended_low | 91 | 2.7 | +0.00049 | 0.56 | +0.45 |
| 45 | F2_fisher_above_rline + F3_above_cloud + F4_extended_low | 71 | 2.1 | +0.00058 | 0.42 | +0.44 |
| 46 | F1_near_resistance + F2_fisher_above_rline + F3_below_cloud | 101 | 3.0 | -0.00050 | 0.52 | -0.43 |
| 47 | F1_near_support | 717 | 21.2 | +0.00020 | 0.53 | +0.42 |
| 48 | F1_near_support + F4_extended_high | 65 | 1.9 | -0.00051 | 0.46 | -0.39 |
| 49 | F2_fisher_below_rline | 1716 | 50.8 | -0.00012 | 0.52 | -0.33 |
| 50 | F1_near_support + F2_fisher_above_rline | 275 | 8.1 | -0.00024 | 0.50 | -0.30 |
| 51 | F1_near_resistance + F2_fisher_above_rline + F4_extended_high | 158 | 4.7 | -0.00029 | 0.46 | -0.28 |
| 52 | F1_near_support + F2_fisher_below_rline + F3_above_cloud | 108 | 3.2 | -0.00021 | 0.50 | -0.28 |
| 53 | F2_fisher_below_rline + F3_below_cloud + F4_extended_low | 270 | 8.0 | +0.00029 | 0.62 | +0.27 |
| 54 | F1_near_support + F2_fisher_above_rline + F4_extended_high | 32 | 0.9 | +0.00049 | 0.53 | +0.26 |
| 55 | F1_near_resistance + F3_below_cloud + F4_extended_low | 29 | 0.9 | +0.00040 | 0.62 | +0.23 |
| 56 | F4_extended_low | 715 | 21.2 | -0.00013 | 0.55 | -0.19 |
| 57 | F2_fisher_above_rline + F3_below_cloud | 635 | 18.8 | +0.00011 | 0.51 | +0.18 |
| 58 | F3_below_cloud | 1335 | 39.5 | +0.00008 | 0.53 | +0.17 |
| 59 | F1_near_resistance + F3_above_cloud | 461 | 13.7 | -0.00006 | 0.47 | -0.11 |
| 60 | F1_near_resistance + F2_fisher_above_rline + F4_extended_low | 37 | 1.1 | +0.00015 | 0.49 | +0.10 |
| 61 | F2_fisher_below_rline + F3_below_cloud | 700 | 20.7 | +0.00006 | 0.55 | +0.10 |
| 62 | F2_fisher_above_rline + F4_extended_high | 441 | 13.1 | +0.00006 | 0.46 | +0.08 |
| 63 | F2_fisher_above_rline | 1661 | 49.2 | -0.00003 | 0.48 | -0.07 |
| 64 | F2_fisher_above_rline + F3_above_cloud | 768 | 22.7 | +0.00002 | 0.47 | +0.03 |

### A.2 Panel 1H N=12 (rows 3,369; calibration bar 3.54)

| # | conditions | n | fire% | mean | hit | t_NW |
|---|---|---|---|---|---|---|
| 1 | F1_near_support + F2_fisher_above_rline + F3_above_cloud | 57 | 1.7 | +0.00394 | 0.61 | +2.09 |
| 2 | F2_fisher_above_rline + F4_extended_low | 278 | 8.3 | -0.00501 | 0.44 | -2.03 |
| 3 | F2_fisher_above_rline + F3_below_cloud + F4_extended_low | 169 | 5.0 | -0.00687 | 0.44 | -1.92 |
| 4 | F1_near_support + F2_fisher_above_rline + F4_extended_low | 78 | 2.3 | -0.00453 | 0.42 | -1.89 |
| 5 | F1_near_resistance + F2_fisher_above_rline + F4_extended_low | 37 | 1.1 | -0.00341 | 0.38 | -1.67 |
| 6 | F1_near_support + F2_fisher_below_rline + F3_above_cloud | 108 | 3.2 | -0.00230 | 0.42 | -1.63 |
| 7 | F1_near_resistance + F3_below_cloud + F4_extended_low | 29 | 0.9 | -0.00416 | 0.48 | -1.42 |
| 8 | F1_near_support + F2_fisher_below_rline + F4_extended_low | 156 | 4.6 | +0.00248 | 0.60 | +1.35 |
| 9 | F1_near_support + F2_fisher_below_rline + F4_extended_high | 33 | 1.0 | -0.00547 | 0.48 | -1.31 |
| 10 | F1_near_support + F3_below_cloud + F4_extended_high | 31 | 0.9 | +0.00368 | 0.71 | +1.31 |
| 11 | F4_extended_low | 711 | 21.1 | -0.00232 | 0.50 | -1.27 |
| 12 | F3_below_cloud + F4_extended_low | 439 | 13.0 | -0.00297 | 0.52 | -1.11 |
| 13 | F1_near_support + F2_fisher_below_rline + F3_below_cloud | 260 | 7.7 | +0.00206 | 0.57 | +1.10 |
| 14 | F1_near_support + F2_fisher_above_rline + F3_below_cloud | 167 | 5.0 | -0.00171 | 0.49 | -0.90 |
| 15 | F1_near_resistance + F2_fisher_above_rline + F4_extended_high | 158 | 4.7 | -0.00134 | 0.44 | -0.88 |
| 16 | F1_near_support + F4_extended_high | 65 | 1.9 | -0.00253 | 0.54 | -0.88 |
| 17 | F1_near_resistance + F4_extended_low | 91 | 2.7 | -0.00156 | 0.48 | -0.84 |
| 18 | F1_near_support + F2_fisher_above_rline | 274 | 8.1 | -0.00107 | 0.49 | -0.77 |
| 19 | F2_fisher_above_rline + F3_below_cloud + F4_extended_high | 94 | 2.8 | +0.00341 | 0.59 | +0.74 |
| 20 | F2_fisher_below_rline + F3_below_cloud + F4_extended_high | 51 | 1.5 | -0.00265 | 0.49 | -0.63 |
| 21 | F2_fisher_above_rline + F3_above_cloud + F4_extended_high | 288 | 8.5 | -0.00085 | 0.49 | -0.61 |
| 22 | F1_near_resistance + F2_fisher_above_rline | 426 | 12.6 | -0.00056 | 0.46 | -0.56 |
| 23 | F2_fisher_above_rline | 1656 | 49.2 | -0.00049 | 0.49 | -0.51 |
| 24 | F1_near_support + F3_above_cloud + F4_extended_low | 44 | 1.3 | -0.00101 | 0.48 | -0.49 |
| 25 | F1_near_resistance + F2_fisher_below_rline + F4_extended_high | 87 | 2.6 | +0.00102 | 0.43 | +0.45 |
| 26 | F1_near_resistance + F2_fisher_below_rline | 317 | 9.4 | +0.00070 | 0.50 | +0.44 |
| 27 | F2_fisher_below_rline + F3_above_cloud + F4_extended_high | 199 | 5.9 | +0.00064 | 0.49 | +0.44 |
| 28 | F1_near_resistance + F3_below_cloud | 158 | 4.7 | -0.00082 | 0.55 | -0.38 |
| 29 | F2_fisher_below_rline + F4_extended_low | 433 | 12.9 | -0.00059 | 0.54 | -0.37 |
| 30 | F1_near_support + F3_above_cloud + F4_extended_high | 18 | 0.5 | -0.00123 | 0.61 | -0.37 |
| 31 | F1_near_support + F3_below_cloud | 427 | 12.7 | +0.00059 | 0.54 | +0.36 |
| 32 | F3_above_cloud | 1482 | 44.0 | +0.00032 | 0.49 | +0.36 |
| 33 | F2_fisher_below_rline + F3_above_cloud | 717 | 21.3 | +0.00037 | 0.51 | +0.35 |
| 34 | F1_near_resistance + F4_extended_high | 245 | 7.3 | -0.00050 | 0.43 | -0.34 |
| 35 | F3_below_cloud + F4_extended_high | 145 | 4.3 | +0.00128 | 0.55 | +0.32 |
| 36 | F1_near_resistance + F2_fisher_above_rline + F3_below_cloud | 101 | 3.0 | -0.00059 | 0.54 | -0.30 |
| 37 | F1_near_resistance + F2_fisher_below_rline + F3_below_cloud | 57 | 1.7 | -0.00122 | 0.56 | -0.30 |
| 38 | F1_near_resistance + F3_above_cloud + F4_extended_high | 179 | 5.3 | -0.00047 | 0.44 | -0.28 |
| 39 | F2_fisher_above_rline + F4_extended_high | 441 | 13.1 | -0.00039 | 0.48 | -0.27 |
| 40 | F2_fisher_above_rline + F3_above_cloud | 765 | 22.7 | +0.00028 | 0.48 | +0.27 |
| 41 | F2_fisher_below_rline + F3_below_cloud | 700 | 20.8 | -0.00042 | 0.55 | -0.26 |
| 42 | F4_extended_high | 741 | 22.0 | -0.00032 | 0.48 | -0.25 |
| 43 | F1_near_support + F3_below_cloud + F4_extended_low | 158 | 4.7 | +0.00059 | 0.58 | +0.25 |
| 44 | F2_fisher_below_rline + F3_below_cloud + F4_extended_low | 270 | 8.0 | -0.00052 | 0.57 | -0.23 |
| 45 | F1_near_resistance + F2_fisher_below_rline + F3_above_cloud | 194 | 5.8 | -0.00037 | 0.47 | -0.22 |
| 46 | F1_near_support + F2_fisher_below_rline | 440 | 13.1 | +0.00029 | 0.52 | +0.21 |
| 47 | F1_near_support | 714 | 21.2 | -0.00023 | 0.51 | -0.20 |
| 48 | F3_above_cloud + F4_extended_high | 487 | 14.5 | -0.00024 | 0.49 | -0.19 |
| 49 | F1_near_support + F2_fisher_above_rline + F4_extended_high | 32 | 0.9 | +0.00050 | 0.59 | +0.19 |
| 50 | F1_near_resistance + F3_above_cloud + F4_extended_low | 43 | 1.3 | +0.00041 | 0.47 | +0.16 |
| 51 | F3_below_cloud | 1335 | 39.6 | -0.00023 | 0.54 | -0.15 |
| 52 | F2_fisher_below_rline + F4_extended_high | 300 | 8.9 | -0.00021 | 0.48 | -0.15 |
| 53 | F1_near_resistance + F2_fisher_below_rline + F4_extended_low | 54 | 1.6 | -0.00030 | 0.56 | -0.13 |
| 54 | F1_near_resistance + F3_above_cloud | 461 | 13.7 | -0.00015 | 0.46 | -0.13 |
| 55 | F1_near_support + F3_above_cloud | 165 | 4.9 | -0.00014 | 0.48 | -0.11 |
| 56 | F1_near_support + F4_extended_low | 234 | 6.9 | +0.00014 | 0.54 | +0.08 |
| 57 | F1_near_resistance + F3_below_cloud + F4_extended_high | 31 | 0.9 | -0.00033 | 0.48 | -0.06 |
| 58 | F2_fisher_below_rline + F3_above_cloud + F4_extended_low | 102 | 3.0 | +0.00009 | 0.49 | +0.05 |
| 59 | F3_above_cloud + F4_extended_low | 172 | 5.1 | +0.00005 | 0.48 | +0.03 |
| 60 | F2_fisher_below_rline | 1713 | 50.8 | +0.00003 | 0.52 | +0.03 |
| 61 | F1_near_resistance | 743 | 22.1 | -0.00003 | 0.48 | -0.03 |
| 62 | F2_fisher_above_rline + F3_below_cloud | 635 | 18.8 | -0.00003 | 0.54 | -0.01 |
| 63 | F1_near_resistance + F2_fisher_above_rline + F3_above_cloud | 267 | 7.9 | +0.00000 | 0.44 | +0.00 |
| 64 | F2_fisher_above_rline + F3_above_cloud + F4_extended_low | 70 | 2.1 | +0.00000 | 0.46 | +0.00 |

### A.3 Panel 4H N=2 (rows 3,378; calibration bar 3.73)

| # | conditions | n | fire% | mean | hit | t_NW |
|---|---|---|---|---|---|---|
| 1 | F1_near_support + F2_fisher_above_rline + F4_extended_low | 75 | 2.2 | -0.00373 | 0.48 | -1.98 |
| 2 | F1_near_resistance + F2_fisher_above_rline + F4_extended_low | 34 | 1.0 | -0.00437 | 0.41 | -1.70 |
| 3 | F1_near_resistance + F2_fisher_above_rline + F3_below_cloud | 119 | 3.5 | +0.00246 | 0.58 | +1.67 |
| 4 | F1_near_resistance + F4_extended_low | 92 | 2.7 | -0.00264 | 0.48 | -1.67 |
| 5 | F3_above_cloud + F4_extended_low | 152 | 4.5 | -0.00206 | 0.49 | -1.65 |
| 6 | F1_near_support + F4_extended_low | 200 | 5.9 | -0.00199 | 0.53 | -1.63 |
| 7 | F1_near_support + F2_fisher_below_rline | 429 | 12.7 | +0.00108 | 0.58 | +1.55 |
| 8 | F2_fisher_above_rline + F3_above_cloud + F4_extended_low | 59 | 1.7 | -0.00329 | 0.42 | -1.51 |
| 9 | F1_near_resistance + F3_below_cloud + F4_extended_low | 26 | 0.8 | -0.00377 | 0.42 | -1.49 |
| 10 | F1_near_resistance + F2_fisher_below_rline + F4_extended_high | 105 | 3.1 | +0.00183 | 0.58 | +1.43 |
| 11 | F1_near_support + F2_fisher_above_rline | 288 | 8.5 | -0.00123 | 0.51 | -1.34 |
| 12 | F1_near_resistance | 838 | 24.8 | +0.00063 | 0.51 | +1.24 |
| 13 | F1_near_support + F2_fisher_below_rline + F3_above_cloud | 106 | 3.1 | +0.00115 | 0.57 | +1.23 |
| 14 | F1_near_support + F3_below_cloud + F4_extended_low | 135 | 4.0 | -0.00194 | 0.52 | -1.22 |
| 15 | F4_extended_high | 932 | 27.6 | +0.00065 | 0.51 | +1.21 |
| 16 | F1_near_resistance + F3_below_cloud + F4_extended_high | 48 | 1.4 | +0.00279 | 0.62 | +1.21 |
| 17 | F3_above_cloud + F4_extended_high | 669 | 19.8 | +0.00074 | 0.50 | +1.21 |
| 18 | F1_near_resistance + F2_fisher_below_rline + F3_above_cloud | 220 | 6.5 | +0.00110 | 0.55 | +1.13 |
| 19 | F1_near_resistance + F4_extended_high | 326 | 9.7 | +0.00083 | 0.50 | +1.11 |
| 20 | F2_fisher_above_rline + F4_extended_low | 262 | 7.8 | -0.00150 | 0.50 | -1.11 |
| 21 | F1_near_resistance + F3_above_cloud | 544 | 16.1 | +0.00069 | 0.50 | +1.10 |
| 22 | F1_near_support + F2_fisher_above_rline + F3_below_cloud | 164 | 4.9 | -0.00147 | 0.50 | -1.10 |
| 23 | F1_near_resistance + F3_above_cloud + F4_extended_low | 49 | 1.5 | -0.00252 | 0.49 | -1.09 |
| 24 | F2_fisher_below_rline | 1595 | 47.2 | +0.00043 | 0.54 | +1.09 |
| 25 | F2_fisher_above_rline + F4_extended_high | 606 | 17.9 | +0.00067 | 0.50 | +1.08 |
| 26 | F1_near_resistance + F3_below_cloud | 168 | 5.0 | +0.00120 | 0.54 | +0.99 |
| 27 | F2_fisher_below_rline + F3_below_cloud | 586 | 17.3 | +0.00075 | 0.56 | +0.99 |
| 28 | F3_below_cloud + F4_extended_high | 143 | 4.2 | +0.00159 | 0.55 | +0.97 |
| 29 | F1_near_support + F3_below_cloud + F4_extended_high | 29 | 0.9 | +0.00341 | 0.66 | +0.96 |
| 30 | F1_near_resistance + F2_fisher_below_rline + F3_below_cloud | 49 | 1.5 | -0.00187 | 0.43 | -0.95 |
| 31 | F1_near_support + F2_fisher_below_rline + F3_below_cloud | 238 | 7.0 | +0.00102 | 0.59 | +0.93 |
| 32 | F1_near_support + F3_above_cloud | 178 | 5.3 | +0.00083 | 0.57 | +0.93 |
| 33 | F1_near_resistance + F2_fisher_above_rline | 511 | 15.1 | +0.00060 | 0.49 | +0.92 |
| 34 | F2_fisher_above_rline + F3_above_cloud + F4_extended_high | 434 | 12.8 | +0.00067 | 0.47 | +0.91 |
| 35 | F2_fisher_below_rline + F3_above_cloud + F4_extended_low | 93 | 2.8 | -0.00129 | 0.53 | -0.87 |
| 36 | F2_fisher_below_rline + F3_below_cloud + F4_extended_high | 49 | 1.5 | +0.00245 | 0.53 | +0.87 |
| 37 | F1_near_resistance + F2_fisher_below_rline | 327 | 9.7 | +0.00066 | 0.53 | +0.87 |
| 38 | F2_fisher_below_rline + F3_above_cloud + F4_extended_high | 235 | 7.0 | +0.00088 | 0.55 | +0.87 |
| 39 | F3_below_cloud | 1239 | 36.7 | +0.00047 | 0.54 | +0.85 |
| 40 | F2_fisher_above_rline + F3_above_cloud | 903 | 26.7 | +0.00044 | 0.49 | +0.85 |
| 41 | F3_above_cloud | 1663 | 49.2 | +0.00031 | 0.50 | +0.82 |
| 42 | F1_near_resistance + F2_fisher_below_rline + F4_extended_low | 58 | 1.7 | -0.00162 | 0.52 | -0.81 |
| 43 | F1_near_support + F2_fisher_below_rline + F4_extended_high | 40 | 1.2 | +0.00193 | 0.55 | +0.80 |
| 44 | F1_near_support + F3_above_cloud + F4_extended_low | 29 | 0.9 | -0.00216 | 0.59 | -0.77 |
| 45 | F2_fisher_below_rline + F4_extended_high | 326 | 9.7 | +0.00060 | 0.53 | +0.67 |
| 46 | F2_fisher_above_rline + F3_below_cloud + F4_extended_high | 94 | 2.8 | +0.00115 | 0.55 | +0.65 |
| 47 | F2_fisher_above_rline + F3_below_cloud + F4_extended_low | 164 | 4.9 | -0.00118 | 0.53 | -0.62 |
| 48 | F1_near_support + F2_fisher_below_rline + F4_extended_low | 125 | 3.7 | -0.00094 | 0.56 | -0.62 |
| 49 | F4_extended_low | 639 | 18.9 | -0.00045 | 0.54 | -0.58 |
| 50 | F2_fisher_above_rline | 1783 | 52.8 | +0.00023 | 0.50 | +0.56 |
| 51 | F2_fisher_below_rline + F3_below_cloud + F4_extended_low | 228 | 6.7 | +0.00066 | 0.55 | +0.53 |
| 52 | F1_near_resistance + F2_fisher_above_rline + F3_above_cloud | 324 | 9.6 | +0.00041 | 0.46 | +0.52 |
| 53 | F1_near_support + F4_extended_high | 88 | 2.6 | +0.00068 | 0.53 | +0.48 |
| 54 | F1_near_resistance + F3_above_cloud + F4_extended_high | 240 | 7.1 | +0.00036 | 0.46 | +0.41 |
| 55 | F1_near_resistance + F2_fisher_above_rline + F4_extended_high | 221 | 6.5 | +0.00036 | 0.46 | +0.40 |
| 56 | F1_near_support + F3_above_cloud + F4_extended_high | 32 | 0.9 | -0.00073 | 0.44 | -0.38 |
| 57 | F2_fisher_below_rline + F4_extended_low | 377 | 11.2 | +0.00029 | 0.56 | +0.33 |
| 58 | F2_fisher_below_rline + F3_above_cloud | 760 | 22.5 | +0.00016 | 0.53 | +0.31 |
| 59 | F2_fisher_above_rline + F3_below_cloud | 653 | 19.3 | +0.00022 | 0.52 | +0.29 |
| 60 | F1_near_support | 717 | 21.2 | +0.00015 | 0.55 | +0.27 |
| 61 | F1_near_support + F2_fisher_above_rline + F4_extended_high | 48 | 1.4 | -0.00035 | 0.52 | -0.22 |
| 62 | F1_near_support + F2_fisher_above_rline + F3_above_cloud | 72 | 2.1 | +0.00034 | 0.58 | +0.20 |
| 63 | F3_below_cloud + F4_extended_low | 392 | 11.6 | -0.00011 | 0.54 | -0.10 |
| 64 | F1_near_support + F3_below_cloud | 402 | 11.9 | +0.00000 | 0.55 | +0.01 |

### A.4 Panel 4H N=6 (rows 3,374; calibration bar 3.76)

| # | conditions | n | fire% | mean | hit | t_NW |
|---|---|---|---|---|---|---|
| 1 | F1_near_resistance + F2_fisher_below_rline + F4_extended_high | 105 | 3.1 | +0.00483 | 0.59 | +2.00 |
| 2 | F1_near_resistance + F3_below_cloud | 168 | 5.0 | +0.00490 | 0.58 | +1.98 |
| 3 | F3_above_cloud + F4_extended_low | 152 | 4.5 | -0.00571 | 0.42 | -1.87 |
| 4 | F1_near_resistance + F2_fisher_above_rline + F3_below_cloud | 119 | 3.5 | +0.00542 | 0.60 | +1.82 |
| 5 | F2_fisher_above_rline + F3_above_cloud + F4_extended_low | 59 | 1.7 | -0.00614 | 0.37 | -1.75 |
| 6 | F3_above_cloud + F4_extended_high | 669 | 19.8 | +0.00258 | 0.54 | +1.53 |
| 7 | F4_extended_high | 932 | 27.6 | +0.00214 | 0.54 | +1.52 |
| 8 | F2_fisher_above_rline + F3_above_cloud + F4_extended_high | 434 | 12.9 | +0.00293 | 0.53 | +1.51 |
| 9 | F1_near_resistance + F2_fisher_above_rline + F4_extended_low | 34 | 1.0 | -0.00671 | 0.35 | -1.50 |
| 10 | F1_near_support + F3_below_cloud + F4_extended_low | 134 | 4.0 | -0.00612 | 0.49 | -1.45 |
| 11 | F2_fisher_above_rline + F3_below_cloud | 649 | 19.2 | +0.00223 | 0.57 | +1.42 |
| 12 | F2_fisher_above_rline + F4_extended_high | 606 | 18.0 | +0.00226 | 0.53 | +1.39 |
| 13 | F2_fisher_below_rline + F3_above_cloud + F4_extended_low | 93 | 2.8 | -0.00543 | 0.45 | -1.38 |
| 14 | F1_near_support + F2_fisher_above_rline + F4_extended_high | 48 | 1.4 | +0.00375 | 0.56 | +1.31 |
| 15 | F1_near_resistance + F4_extended_high | 326 | 9.7 | +0.00223 | 0.51 | +1.29 |
| 16 | F2_fisher_above_rline | 1779 | 52.7 | +0.00120 | 0.53 | +1.27 |
| 17 | F3_below_cloud | 1235 | 36.6 | +0.00172 | 0.55 | +1.25 |
| 18 | F1_near_support + F4_extended_low | 199 | 5.9 | -0.00385 | 0.52 | -1.22 |
| 19 | F1_near_resistance | 838 | 24.8 | +0.00128 | 0.52 | +1.15 |
| 20 | F1_near_support + F2_fisher_below_rline + F4_extended_low | 125 | 3.7 | -0.00515 | 0.51 | -1.14 |
| 21 | F1_near_resistance + F3_below_cloud + F4_extended_high | 48 | 1.4 | +0.00605 | 0.56 | +1.10 |
| 22 | F1_near_resistance + F3_above_cloud + F4_extended_low | 49 | 1.5 | -0.00541 | 0.41 | -1.05 |
| 23 | F2_fisher_below_rline + F4_extended_high | 326 | 9.7 | +0.00192 | 0.55 | +1.04 |
| 24 | F1_near_resistance + F2_fisher_below_rline + F3_above_cloud | 220 | 6.5 | +0.00186 | 0.55 | +1.03 |
| 25 | F1_near_resistance + F2_fisher_below_rline + F3_below_cloud | 49 | 1.5 | +0.00363 | 0.55 | +1.01 |
| 26 | F1_near_resistance + F4_extended_low | 92 | 2.7 | -0.00320 | 0.46 | -0.98 |
| 27 | F2_fisher_below_rline + F3_above_cloud + F4_extended_high | 235 | 7.0 | +0.00194 | 0.57 | +0.95 |
| 28 | F1_near_resistance + F2_fisher_below_rline | 327 | 9.7 | +0.00147 | 0.54 | +0.95 |
| 29 | F2_fisher_below_rline + F4_extended_low | 377 | 11.2 | -0.00229 | 0.52 | -0.95 |
| 30 | F1_near_support + F3_above_cloud + F4_extended_low | 29 | 0.9 | -0.00390 | 0.52 | -0.92 |
| 31 | F1_near_resistance + F2_fisher_above_rline | 511 | 15.1 | +0.00116 | 0.51 | +0.87 |
| 32 | F4_extended_low | 638 | 18.9 | -0.00162 | 0.52 | -0.86 |
| 33 | F3_above_cloud | 1663 | 49.3 | +0.00088 | 0.52 | +0.84 |
| 34 | F1_near_support + F3_below_cloud + F4_extended_high | 29 | 0.9 | +0.00367 | 0.55 | +0.83 |
| 35 | F1_near_support + F2_fisher_below_rline + F3_above_cloud | 106 | 3.1 | +0.00180 | 0.60 | +0.80 |
| 36 | F1_near_resistance + F3_above_cloud + F4_extended_high | 240 | 7.1 | +0.00151 | 0.50 | +0.78 |
| 37 | F2_fisher_above_rline + F3_above_cloud | 903 | 26.8 | +0.00100 | 0.51 | +0.77 |
| 38 | F2_fisher_below_rline | 1595 | 47.3 | +0.00079 | 0.53 | +0.74 |
| 39 | F1_near_resistance + F3_above_cloud | 544 | 16.1 | +0.00098 | 0.51 | +0.74 |
| 40 | F1_near_support + F2_fisher_above_rline + F3_below_cloud | 162 | 4.8 | +0.00177 | 0.55 | +0.65 |
| 41 | F1_near_support + F2_fisher_above_rline + F4_extended_low | 74 | 2.2 | -0.00164 | 0.53 | -0.60 |
| 42 | F2_fisher_below_rline + F3_below_cloud | 586 | 17.4 | +0.00116 | 0.53 | +0.59 |
| 43 | F1_near_support + F2_fisher_above_rline + F3_above_cloud | 72 | 2.1 | -0.00213 | 0.46 | -0.57 |
| 44 | F2_fisher_below_rline + F3_above_cloud | 760 | 22.5 | +0.00074 | 0.53 | +0.57 |
| 45 | F1_near_support + F4_extended_high | 88 | 2.6 | +0.00134 | 0.52 | +0.53 |
| 46 | F1_near_resistance + F2_fisher_above_rline + F4_extended_high | 221 | 6.6 | +0.00100 | 0.47 | +0.48 |
| 47 | F1_near_support + F2_fisher_below_rline + F3_below_cloud | 238 | 7.1 | -0.00132 | 0.53 | -0.46 |
| 48 | F3_below_cloud + F4_extended_high | 143 | 4.2 | +0.00166 | 0.52 | +0.43 |
| 49 | F2_fisher_above_rline + F3_below_cloud + F4_extended_high | 94 | 2.8 | +0.00198 | 0.54 | +0.41 |
| 50 | F1_near_support + F2_fisher_below_rline + F4_extended_high | 40 | 1.2 | -0.00156 | 0.47 | -0.39 |
| 51 | F2_fisher_below_rline + F3_below_cloud + F4_extended_low | 228 | 6.8 | -0.00126 | 0.55 | -0.38 |
| 52 | F3_below_cloud + F4_extended_low | 391 | 11.6 | -0.00095 | 0.54 | -0.38 |
| 53 | F2_fisher_above_rline + F4_extended_low | 261 | 7.7 | -0.00065 | 0.52 | -0.32 |
| 54 | F1_near_resistance + F2_fisher_below_rline + F4_extended_low | 58 | 1.7 | -0.00115 | 0.52 | -0.30 |
| 55 | F1_near_support + F3_above_cloud + F4_extended_high | 32 | 0.9 | -0.00149 | 0.47 | -0.29 |
| 56 | F1_near_resistance + F2_fisher_above_rline + F3_above_cloud | 324 | 9.6 | +0.00039 | 0.49 | +0.24 |
| 57 | F1_near_support + F2_fisher_above_rline | 286 | 8.5 | -0.00046 | 0.51 | -0.23 |
| 58 | F2_fisher_below_rline + F3_below_cloud + F4_extended_high | 49 | 1.5 | +0.00106 | 0.49 | +0.22 |
| 59 | F2_fisher_above_rline + F3_below_cloud + F4_extended_low | 163 | 4.8 | -0.00052 | 0.54 | -0.20 |
| 60 | F1_near_support + F2_fisher_below_rline | 429 | 12.7 | +0.00020 | 0.56 | +0.11 |
| 61 | F1_near_support + F3_above_cloud | 178 | 5.3 | +0.00021 | 0.54 | +0.11 |
| 62 | F1_near_resistance + F3_below_cloud + F4_extended_low | 26 | 0.8 | +0.00019 | 0.46 | +0.05 |
| 63 | F1_near_support | 715 | 21.2 | -0.00007 | 0.54 | -0.04 |
| 64 | F1_near_support + F3_below_cloud | 400 | 11.9 | -0.00007 | 0.54 | -0.03 |

## Appendix B: git commits

1. `research: factor-correlation study pre-registration (protocol frozen before results)` (0f21aac)
2. `research: frozen candle snapshots + prereg hash recorded` (d115264)
3. `research: exploration results + null-result findings doc` (this commit)
