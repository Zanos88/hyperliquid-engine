# Factor Confirmatory Tests (Round 2) — "Washed-Out Dip Near Support"

Study date: 2026-07-09. Status: **RESEARCH ONLY — pre-registered; results
pending.** Follows docs/FACTOR_CORRELATION_STUDY.md (round 1, null result).

> **RESEARCH — NO TRADING IMPACT.** No trades, no strategy module, no DB.
> Frozen historical Hyperliquid candles; descriptive statistics; no cost
> model. A fail on any or all tests is a valid and expected outcome.

## 1. Question & scope

Round 1's exploration produced no cell that cleared its multiplicity
calibration bar, but its best-looking cell — long when **Fisher ≤ −2.0 AND
Fisher below its R-line AND close in the bottom quarter of the local S/R
range** (1H N=4: t_NW +2.59, hit 0.68, n=157) — is a coherent hypothesis:
a washed-out dip into support mean-reverts upward. Round 2 asks exactly one
question, three times, on data the rule has never been selected on: does
that rule, **unchanged**, predict positive 4-bar forward returns?

Three one-shot tests, no sweep, no tuning:

- **Test 0 — 1H holdout (direct confirmation, reported first):** same rule,
  same TF where it was found, on the round-1 frozen 1H snapshot's untouched
  holdout. The holdout window entirely postdates the discovery window —
  genuinely unseen data. The cleanest of the three.
- **Test 1 — 4H holdout (generalization):** same-TF structure, round-1
  frozen 4H snapshot's untouched holdout.
- **Test 2 — 12H full series (generalization):** a series never fetched
  before round 2; the whole post-warm-up history is the test set.

**Prior evidence, stated before running:** round-1 exploration saw this
rule **negative on 4H** (t −0.62 at N=2, −1.14 at N=6, n=125) and positive
only on 1H. Test 1 runs against that prior. The three tests are partially
dependent (overlap structure in §2.4), not independent replications.

## 2. Pre-registration (frozen before any test ran)

Operative pre-registration: the constants block in
`scripts/confirmatory_rule_test.py`. Pre-registration commit:
`1b8348c` (script + this section committed before `--phase run`).
The script's `--phase selfcheck` asserts the rule's three conditions still
resolve to the round-1 threshold triples — the rule is imported, not
redefined.

### 2.1 Rule (identical in all three tests)

Fire **long** at bar i when all three hold (round-1 factor definitions,
byte-identical — same-TF structure from `compute_bias` on the trailing
300-bar slice, `fisher_transform(period=10)`, row start i ≥ 120):

| Condition | Definition |
|---|---|
| F4_extended_low | Fisher level ≤ −2.0 |
| F2_fisher_below_rline | Fisher − R-line < 0 (below its 1-bar-delayed trigger line) |
| F1_near_support | (close − nearest support)/(nearest resistance − nearest support) ≤ 0.25 |

### 2.2 Target, statistic, pass bar

- Target: forward log return `ln(close[i+4]/close[i])` — **N = 4 bars in
  all three tests**, the discovery cell's own horizon, zero per-TF
  adaptation (4h clock on 1H, 16h on 4H, 2d on 12H).
- Statistic: conditional mean with the round-1 Newey–West (Bartlett)
  t-stat, lag = 3. Hit rate = fraction of firings with positive forward
  return. Secondary descriptive: 4-phase non-overlapping subsample means.
- **Pass, per test: mean > 0 AND t_NW ≥ 2.0** (sign-restricted, standard
  significance). Reported regardless of outcome.

### 2.3 Data windows (no other window, horizon, threshold, or TF is evaluated)

| Test | Series | Rows | Window (close times) | Projected firings |
|---|---|---|---|---|
| 0 | round-1 frozen 1H snapshot, holdout: 3501 ≤ i ≤ 4997 | ~1,497 | 2026-05-07 → 2026-07-08 | ~70 (4.65% expl. fire rate) |
| 1 | round-1 frozen 4H snapshot, holdout: 3500 ≤ i ≤ 4995 | ~1,496 | 2025-11-01 → 2026-07-08 | ~55 (3.70%) |
| 2 | fresh frozen 12H snapshot, full: 120 ≤ i ≤ n−5 | ~3,175 | 2022-03 → 2026-07 | ~100–130 |

Holdout **factors** may look back across the split boundary
(backward-looking history, not leakage); only targets stay inside the
window. History check preceding TF selection (read-only, run before this
pre-registration): 12h → 3,300 bars 2022-01-01→2026-07-08, gaps 0; 1d →
2,150 bars 2020-08-19→2026-07-08, gaps 0. Both usable; **12H chosen for
power** (user decision).

### 2.4 Dependence & joint false-positive disclosure (3 tests)

Overlap structure: Test 0's window is fully unseen and postdates discovery.
Test 1's window overlaps ~59% of its calendar span with the 1H
**exploration** window that produced the rule, and contains Test 0's window
(Tests 0 and 1 overlap each other, 2026-05 → 2026-07). Test 2's series
contains both round-1 windows but adds ~2.2 years (2022-01 → 2024-03) of
never-before-fetched history — roughly half its rows. These are **cross-TF
consistency tests on partially overlapping history**, not three independent
replications.

False-positive arithmetic: the pass bar is sign-restricted, so the
per-test false-positive probability under the null is P(t ≥ +2.0) ≈ 2.28%
(one-sided). Family-wise chance of ≥ 1 false pass across three tests:
**at most 6.7%** under independence (1 − 0.9772³ = 0.0669), shrinking
toward ~2.3% under the strong positive dependence induced by the
overlapping windows — honest statement: **roughly 2–7%**. (A sign-agnostic
|t| ≥ 2 bar would have been ~4.55% per test → ~13.1% family-wise; that is
not the bar used.) Bonferroni reference at family α = 0.05, one-sided,
3 tests: t ≈ 2.13 — reported for context, not used as the bar.

### 2.5 One-shot enforcement

Each test's result is written to a write-once file
(`research/output/confirm_{1h,4h,12h}.json`); `--phase run` refuses to
execute if **any** of the three exists, and there is deliberately no
`--force` this round. A re-run is a new study, not a reproduction.

## 3. Results

*(filled after the single `--phase run`)*

### 3.1 Test 0 — 1H holdout (direct confirmation)

TBD

### 3.2 Generalization tests (Test 1 — 4H holdout; Test 2 — 12H full series)

TBD

## 4. Findings (honest read)

*(filled after results)*

## 5. Limitations

- Same as round 1 (docs/FACTOR_CORRELATION_STUDY.md §10) plus: partial
  calendar dependence between the three tests (§2.4); Test 2's window
  includes strong-drift regimes (2023–24, 2025–26) — its unconditional
  mean is the baseline to read its conditional mean against; ~55–70
  firings per holdout test detect only large edges (round-1 MDE logic).

## 6. Reproduce

```powershell
python scripts/confirmatory_rule_test.py --phase selfcheck
python scripts/confirmatory_rule_test.py --phase run   # refuses: outputs exist (one-shot)
```

Frozen inputs: `research/data/BTC_{1h,4h,12h}_snapshot.json`. Results:
`research/output/confirm_{1h,4h,12h}.json`.

## Appendix: git commits

1. `research(r2): confirmatory-test pre-registration` (1b8348c)
2. TBD (12H snapshot)
3. TBD (results)
