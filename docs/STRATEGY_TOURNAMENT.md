# Strategy Tournament (Round 3) — Classic Trend/Momentum, Pre-registered

Study date: 2026-07-09. Status: **RESEARCH ONLY — pre-registered; results
pending.** Follows FACTOR_CORRELATION_STUDY.md (round 1, null) and
FACTOR_CONFIRMATORY_TESTS.md (round 2, 0/3 falsified).

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

*(filled after `--phase explore`)*

## 4. Selection

*(filled after mechanical selection)*

## 5. Holdout confirmation

*(filled after the single `--phase confirm`, if a variant is selected)*

## 6. Findings (honest read)

*(filled last)*

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
2. TBD (1D snapshot)
3. TBD (results)
