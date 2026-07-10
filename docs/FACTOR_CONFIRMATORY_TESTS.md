# Factor Confirmatory Tests (Round 2) — "Washed-Out Dip Near Support"

> **SUPERSEDED 2026-07-10:** results below were computed under the Fisher gain bug (fixed in 9da31ee - the recursion applied Ehlers' x2 twice, saturating the indicator). Corrected re-run results and the full blast-radius report: docs/FISHER_FIX_REVERIFICATION.md.

Study date: 2026-07-09. Status: **RESEARCH ONLY — COMPLETE. Result: 0/3
FAIL — every test's conditional mean was NEGATIVE; the hypothesis is
falsified.** Follows docs/FACTOR_CORRELATION_STUDY.md (round 1, null result).

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

Single `--phase run`, 2026-07-09, all three tests in one invocation.
**0/3 passed** at the pre-registered bar (mean > 0 AND t_NW ≥ 2.0).

### 3.1 Test 0 — 1H holdout (direct confirmation): **FAIL**

| Window | Rows | Uncond. mean | n | Fire rate | Mean | Hit rate | t_NW | Verdict |
|---|---|---|---|---|---|---|---|---|
| 2026-05-07 → 2026-07-08 | 1,497 | −0.00068 | 56 | 3.7% | **−0.00246** | **0.48** | **−1.94** | **FAIL** |

Not a marginal miss — a full sign reversal. The discovery cell was
+0.00243 mean / 0.68 hit / t +2.59 in exploration; on genuinely unseen
rows of the *same timeframe* the identical rule produced −0.00246 mean /
0.48 hit / t −1.94, i.e. nearly significant in the **wrong** direction,
and worse than the window's unconditional baseline (−0.00068). Every one
of the four non-overlapping phase subsamples is negative (−0.0037, −0.0018,
−0.0026, −0.0020).

### 3.2 Generalization tests: **FAIL, FAIL**

| Test | Window | Rows | Uncond. mean | n | Fire rate | Mean | Hit | t_NW | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 — 4H holdout | 2025-11-01 → 2026-07-08 | 1,496 | −0.00154 | 59 | 3.9% | −0.00308 | 0.46 | −0.81 | FAIL |
| 2 — 12H full | 2022-03-02 → 2026-07-06 | 3,176 | **+0.00046** | 109 | 3.4% | −0.00195 | 0.53 | −0.37 | FAIL |

Test 1 is consistent with its stated prior (the rule was already negative
on 4H exploration). Test 2 is the broadest window (4.4 years, ~half never
fetched before round 2) and the firing bars underperform a *positive*
unconditional baseline by ~0.24% per 2-day window. Eleven of the twelve
phase subsamples across the three tests have negative means.

## 4. Findings (honest read)

1. **The hypothesis is falsified — decisively, not marginally.** Zero of
   three pre-registered tests passed; all three conditional means are
   negative; all three sit below their windows' unconditional baselines.
   "Fisher ≤ −2, below R-line, near support" does not predict positive
   4-bar forward returns on any timeframe tested. If the data weakly
   suggest anything, it is the opposite: a washed-out dip near support
   tends to keep falling over the next 4 bars.
2. **Test 0 is the textbook exploration-artifact signature.** Same rule,
   same timeframe, adjacent time period: t +2.59 in-sample → t −1.94
   out-of-sample. Round 1's calibration bar (which said a +2.59 cell
   appears in about half of shuffled datasets) was right to reject this
   cell, and the confirmatory test now demonstrates *why* empirically.
3. **The failure is consistent, not window-specific.** Three timeframes,
   windows spanning 2022–2026 including ~2.2 years never seen by any prior
   phase of this program, 11/12 negative phase subsamples. "Unlucky
   window" is hard to sustain.
4. **Do not flip the sign.** A short version of this rule ("knife keeps
   falling") would be a *new* hypothesis mined from these confirmatory
   results — running it on this same data would be exactly the selection
   loop this program is built to avoid. It would need its own
   pre-registration on data these tests haven't consumed.
5. **This closes the confluence-weighting thread for these four factors.**
   Round 1: no factor or 64-cell combination cleared chance-calibrated
   bars anywhere. Round 2: the single best exploration cell failed 0/3
   confirmatory tests with reversed sign. Track 4 (weighted confluence on
   these factors) has no empirical support; further rounds should change
   the factor set or the question, not re-test this rule.

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
2. `research(r2): frozen 12H snapshot + prereg hash recorded` (863c2cd)
3. `research(r2): results — 0/3 fail, hypothesis falsified` (this commit)
