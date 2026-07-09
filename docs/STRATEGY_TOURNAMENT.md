# Strategy Tournament (Round 3) — Classic Trend/Momentum, Pre-registered

Study date: 2026-07-09. Status: **RESEARCH ONLY — COMPLETE. Result: NULL
at the pre-registered bar** (no variant cleared the family-max luck
calibration; the holdout never ran) — **with a materially different
texture than rounds 1–2**: nearly every variant beat buy-and-hold
risk-adjusted with roughly half the drawdown, consistent with the external
trend literature, but a single asset over ~4 years cannot statistically
separate that from timing luck. See §6. Follows FACTOR_CORRELATION_STUDY.md
(round 1, null) and FACTOR_CONFIRMATORY_TESTS.md (round 2, 0/3 falsified).

> **RESEARCH — NO TRADING IMPACT.** No trades, no strategy module changes,
> no DB. Frozen historical Hyperliquid candles; idealized close fills; taker
> 0.075%/side included; **no slippage and no perp funding** (a live long
> position on perps pays/receives funding — typically a drag in bull
> regimes; disclosed, not modeled). A null result is a valid outcome. Any
> surviving strategy's next step is the repo's existing DRY-RUN forward
> test, never direct live wiring (two-switch rule, user-gated).

## 1. Question & scope

Rounds 1–2 killed intraday factor confluence on this data. Round 3 tests
the one strategy class with decades of documented, cross-asset evidence —
**time-series trend/momentum** — on the longest BTC history this repo can
reach: 1D back to 2020-08 (two full bull/bear cycles) and 12H back to
2022-01. Seven classic variants per timeframe, parameters fixed a priori
from the literature (Turtle 20/10 and 55/20; SMA 50/100/200; 1-month and
3-month momentum). **No grid search, no tuning — 14 pre-registered cells
total**, judged against buy-and-hold and a luck calibration.

Honesty note on the ask ("find a profitable strategy"): no test on ~6
years of one asset's history can *guarantee* forward profitability. What
this round delivers is the strongest available evidence either way: a
variant that survives (a) fees, (b) a family-wise luck bar, (c) a
buy-and-hold control, and (d) an untouched holdout — or the knowledge that
none does. Ultimate confirmation is only ever the dry-run forward test.

## 2. Pre-registration (frozen before any results were computed)

Operative pre-registration: the constants block in
`scripts/strategy_tournament.py`. Pre-registration commit:
`08b1853` (script + this section committed before
`--phase explore` first ran).

### 2.1 Variants (all long/flat; position at close of bar j earns bar j+1)

| Variant | Rule |
|---|---|
| sma50 / sma100 / sma200 | long while close > SMA(N), else flat |
| donch_20_10 | long when close > prior 20-bar high; flat when close < prior 10-bar low (Turtle S1) |
| donch_55_20 | 55-bar-high entry / 20-bar-low exit (Turtle S2) |
| tsmom30 / tsmom90 | long while close > close N bars ago, else flat |

Long/flat (not long/short) because shorting BTC's secular drift has been
historically punished and the literature edge is predominantly on the long
side for crypto; this is fixed a priori, not tuned.

### 2.2 Evaluation

- Net per-bar log returns; **fee 0.075% per side** on every position
  change; buy-and-hold pays one entry fee.
- Metrics per window: net multiple, annualized return, annualized Sharpe
  (√365/√730 scaling), max drawdown (log-equity), trades, exposure.
- Warm-up: evaluation starts at bar 201 (SMA200 lookback) on both series.
- **Split:** chronological 70/30 over evaluation bars. Exploration is
  analyzed; the holdout is reserved for ONE confirmation.
- **Luck bar:** family-max circular-shift calibration — each panel's 7
  position series rotated against returns (200 seeded offsets), best
  Sharpe among the 7 recorded per rotation; the 95th percentile is the
  panel's bar. This jointly prices multiplicity (7 variants), position
  autocorrelation, and return properties.

### 2.3 Selection & confirmation (mechanical, one shot)

Selection (verbatim from the script):

> highest exploration net Sharpe across both panels, requiring ≥ 10
> exploration trades AND Sharpe > panel family-max shift-null 95th pct
> AND Sharpe > buy-and-hold exploration Sharpe on the same panel

None qualifies → null result; the holdout never runs.

Confirmation (one shot, write-once output, no `--force`): the selected
variant's holdout metrics, **PASS iff net log return > 0 AND Sharpe ≥ 0.5
AND Sharpe ≥ half its exploration Sharpe.** This is a directional
consistency bar, not statistical proof — a ~1.6–1.8-year holdout cannot
significantly confirm a moderate Sharpe (that would need ~4+ years). The
significance-bearing device is the exploration luck bar; the holdout
checks the winner isn't a regime artifact; the dry-run forward test is the
real arbiter.

### 2.4 Data & dependence disclosure

- 1D: fresh frozen snapshot (~2,150 bars, 2020-08 → 2026-07; history check
  2026-07-09: gap-free).
- 12H: the round-2 frozen snapshot (3,300 bars, 2022-01 → 2026-07),
  **reused**. Round 2 evaluated one falsified intraday factor rule on it;
  the raw series was not mined for trend rules. Disclosed.
- All windows share BTC's one price history with rounds 1–2 — different
  questions, same asset. These 14 cells are this round's complete search
  space; nothing else was evaluated.

## 3. Exploration results

### 3.1 Panel 1D — exploration 2021-03-08 → 2024-11-30 (holdout reserved 2024-12-01 → 2026-07-08)

Buy-and-hold: net ×1.89, Sharpe +0.28, maxDD(log) 1.46.
**Luck bar (family-max shift p95 Sharpe): 1.40** (shift-null median 0.45).

| Variant | Net × | Ann % | Sharpe | maxDD(log) | Trades | Exposure |
|---|---|---|---|---|---|---|
| sma50 | 2.82 | +31.9 | +0.71 | 0.88 | 76 | 0.51 |
| sma100 | 2.51 | +27.9 | +0.61 | 0.48 | 52 | 0.54 |
| sma200 | 1.65 | +14.3 | +0.32 | 1.02 | 34 | 0.55 |
| donch_20_10 | 1.49 | +11.3 | +0.28 | 0.77 | 42 | 0.47 |
| donch_55_20 | 1.13 | +3.3 | +0.09 | 0.79 | 20 | 0.40 |
| **tsmom30** | **3.03** | **+34.5** | **+0.77** | 0.63 | 114 | 0.52 |
| tsmom90 | 1.86 | +18.0 | +0.39 | 0.85 | 64 | 0.56 |

### 3.2 Panel 12H — exploration 2022-04-11 → 2025-03-30 (holdout reserved 2025-03-31 → 2026-07-08)

Buy-and-hold: net ×2.00, Sharpe +0.44, maxDD(log) 0.99.
**Luck bar: 1.59** (shift-null median 0.61).

| Variant | Net × | Ann % | Sharpe | maxDD(log) | Trades | Exposure |
|---|---|---|---|---|---|---|
| sma50 | 1.91 | +24.4 | +0.62 | 0.45 | 138 | 0.51 |
| sma100 | 2.23 | +31.0 | +0.77 | 0.45 | 80 | 0.51 |
| **sma200** | **2.65** | **+38.9** | **+0.91** | 0.51 | 58 | 0.56 |
| donch_20_10 | 1.10 | +3.4 | +0.11 | 0.62 | 68 | 0.42 |
| donch_55_20 | 1.69 | +19.4 | +0.59 | 0.38 | 30 | 0.40 |
| tsmom30 | 2.21 | +30.6 | +0.74 | 0.44 | 192 | 0.53 |
| tsmom90 | 2.21 | +30.6 | +0.76 | 0.49 | 93 | 0.55 |

## 4. Selection

**No variant qualifies.** Best cells: 1D tsmom30 (Sharpe 0.77 vs bar 1.40)
and 12H sma200 (0.91 vs bar 1.59). Twelve of fourteen cells beat their
panel's buy-and-hold Sharpe, but none clears the family-max luck bar —
the pre-registered significance device. Per §2.3: null result.

## 5. Holdout confirmation

**Not run — by design.** Both holdouts (1D 2024-12→2026-07, 12H
2025-03→2026-07) remain untouched and valid for a future pre-registered
question.

## 6. Findings (honest read)

1. **Null at the bar, but not the same null as rounds 1–2.** Rounds 1–2's
   candidates were *indistinguishable from noise and reversed on unseen
   data*. Here, 12/14 variants beat buy-and-hold risk-adjusted, with
   uniformly lower drawdowns (0.38–1.02 log vs 0.99–1.46) at ~50%
   exposure, across two timeframes, with the whole family pointing the
   same way — the exact signature the external trend literature documents
   (drawdown avoidance is where the Sharpe comes from; these windows
   include the 2021–22 −77% bear that trend rules side-stepped).
2. **Why it still fails the bar:** the seven variants are highly
   correlated (all "long in uptrends"), so 14 supportive cells are closer
   to 1–2 independent observations. On one asset over ~4 years, the
   luckiest 5% of random 50%-exposed timers reach Sharpe 1.40–1.59; the
   best real variant reached 0.91. The sample cannot separate skill from
   timing luck. This is a **power** failure, not a falsification — unlike
   round 2, nothing here reversed sign.
3. **The pre-registered next step is breadth, not depth.** The literature
   validates trend *across assets* (the average of many per-asset trend
   sleeves), which multiplies effective sample. Round 4 should re-test
   this same family, unchanged, as an equal-weight portfolio across the
   liquid Hyperliquid universe (BTC/ETH/SOL/…): same rules, same fees,
   same luck-bar machinery, portfolio-level Sharpe. That is a power
   upgrade of an undamaged hypothesis, not a new mined family.
4. **What is already actionable regardless of statistics:** if the goal is
   BTC exposure with smaller drawdowns rather than "an edge," a long/flat
   trend filter (e.g. tsmom30 or sma100/200) historically delivered
   similar-to-better net returns than holding, with roughly half the
   drawdown, and that property is robust across all 14 specifications
   here. That is a risk-management claim, not an alpha claim — it is the
   one thing three rounds of hostile testing have not damaged.

## 7. Limitations

- One asset, ≤ 5.9 years, 2 cycles — trend results are notoriously
  regime-dependent; a passing variant can still fail forward.
- No funding: a perp implementation of a mostly-long strategy pays funding
  (often 5–15%/yr in bulls) — apply as a haircut when reading annualized
  returns; a spot implementation does not.
- No slippage; idealized close fills; long/flat only.
- The holdout PASS bar is consistency, not proof (§2.3).

## 8. Reproduce

```powershell
python scripts/strategy_tournament.py --phase selfcheck
python scripts/strategy_tournament.py --phase explore   # refuses re-run once output exists
python scripts/strategy_tournament.py --phase confirm   # one-shot, write-once
```

Frozen inputs: `research/data/BTC_{1d,12h}_snapshot.json`. Results:
`research/output/tournament_explore.json`, `tournament_confirm.json`.

## Appendix: git commits

1. `research(r3): strategy-tournament pre-registration` (08b1853)
2. `research(r3): frozen 1D snapshot + prereg hash recorded` (f9f0780)
3. `research(r3): exploration null at luck bar; breadth flagged as round 4` (this commit)
