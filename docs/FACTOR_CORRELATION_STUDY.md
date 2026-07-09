# Factor Correlation Study — Confluence Factors vs Forward Returns

Study date: 2026-07-09. Status: **RESEARCH ONLY.**

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

*(filled after `--phase fetch`)*

| | 1H | 4H |
|---|---|---|
| Snapshot file | `research/data/BTC_1h_snapshot.json` | `research/data/BTC_4h_snapshot.json` |
| Fetched at (UTC) | TBD | TBD |
| Bars | TBD | TBD |
| Window | TBD | TBD |
| Split index / date | TBD | TBD |

Per-factor exclusion counts per split: see §5/§6 (F1's undefined-at-breakout
rate is a first-class reported number, not silently dropped rows).

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

*(filled after `--phase explore`)*

## 6. Exploration results — 4H

*(filled after `--phase explore`)*

## 7. Candidate rule

*(filled after mechanical selection; includes prior expectation written
before the holdout runs, or "no candidate met criteria")*

## 8. Holdout result

*(filled after the single `--phase holdout` run)*

## 9. Findings (honest read)

*(filled last)*

## 10. Limitations & threats to validity

- **Overlapping targets / effective sample:** all t-stats are NW-adjusted,
  but n_eff ≈ n/N still bounds what is knowable; see the MDE statement in §4.
- **Single-regime 1H window:** ~208 days of 1H data is one market regime;
  the 4H series (~2.3 years) is the only multi-regime view.
- **Multiplicity:** 64 cells × 4 panels; the calibration bar and exceedance
  counts are mitigations, not cures. Only the single holdout test is
  inference-grade.
- **Self-contained structure (F1):** deviates from the production
  4H-structure-for-1H pairing by design (clean per-TF comparability); the
  production pairing is untested here.
- **Economic vs statistical significance:** no cost model — a supported
  cell is a statistical statement about raw forward returns, not a claim
  that a strategy would net positive after fees/slippage.
- **Snapshot specificity:** results are conditional on this exact frozen
  window; Hyperliquid retention makes the 1H window unrepeatable later.

## 11. Reproduce

```powershell
python scripts/factor_correlation_study.py --phase selftest
python scripts/factor_correlation_study.py --phase fetch      # refreshes snapshots (new window = new study)
python scripts/factor_correlation_study.py --phase explore --tf both
python scripts/factor_correlation_study.py --phase holdout    # one-shot; write-once guarded
```

Frozen inputs/outputs are committed under `research/data/` and
`research/output/`.

## 12. Open items / future work

1. F1 from 4H structure for 1H bars (the production bias/trigger pairing) —
   worth testing only if F1 shows anything here.
2. Alternative targets (ATR-normalized returns, max-favorable-excursion)
   — out of scope round 1 by pre-registration.
3. If a candidate survives the holdout: a Track 4 weighted-confluence
   design doc — separate build, separately reviewed, backtest-only first.

## Appendix A: full 64-cell tables (all four panels, nulls included)

*(filled after `--phase explore`; committed verbatim in
`research/output/explore_{1h,4h}.json`)*

## Appendix B: git commits

*(filled at completion)*
