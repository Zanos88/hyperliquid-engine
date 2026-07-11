# Track 4-Comp — Stop-Based Mean-Reversion Rebuild

Run 2026-07-11, corrected Fisher. **Final verdict up front: a
comp-compliant version of this edge does NOT survive in economically
meaningful form.** The reason is structural and worth the read: at wide
stops the winners survive — it's the R-economics of the first-profit exit
that fail. Backtest only; SIMULATED (idealized fills incl. stops filled AT
the level — no slippage/gap modeling, which for stop designs is
load-bearing and would only worsen these numbers).

**Prior-art distinction from Track 3 (stated up front, per brief):** Track 3
was Fisher-exhaustion + structural (Fib/S-R) bias at −2.0 (fires ~4×/yr)
with a long/short cycling state machine — near-total null post-fix. This
uses SMA bias, the −1.25 threshold (14.7% of 4H bars), and single
entry/exit per trade. Related family, materially different test.

## Stop widths — fixed by rule from Round 4's real MAE data

Every Round-4 trade's MAE expressed in ATR-at-entry multiples: 16 of 17
winners sit ≤ 3.11×; the 2024-08-27 hostage is a 13.92× outlier.
Pre-registered selection rule (p50-clearing / p90-clearing /
all-but-hostage, rounded up to 0.5; deterministic midpoint tie-break when
p90 = all-but-hostage): **stops = 1.0×, 2.0×, 3.5× ATR.** Design: entry
unchanged (4H Fisher ≤ −1.25, 12H SMA30, long-only); exit = first of
{stop, first-profit, Fisher-reversal}; risk-per-trade sizing
(notional = risk_pct / stop-distance, capped at 100% capital — no
leverage; cap-bind counts reported). Round-4 regression with stop=None
re-verified byte-identical before any run.

## The load-bearing table: what each stop does to the 17 baseline winners

| Stop | Kept as winner | Cut into loss | New trades admitted¹ | Sum R | Avg win (R) |
|---|---|---|---|---|---|
| 1.0×ATR | 10 | **7** | 3 (of which 2 more stopped) | **−6.98R** | +0.28R |
| 2.0×ATR | 15 | 2 | 0 | **−0.07R** | +0.14R |
| 3.5×ATR | 16 | 1 (the Aug-27 hostage only) | 0 | **+0.44R** | +0.09R |

¹ Stop-outs free the position slot early, admitting entries the no-stop
baseline never took.

## Comp-safety per cell (Gold 2-Step budgets: 8% trailing / 5% daily)

| Stop | Risk/trade | Total P&L (% capital, 2.28y) | maxDD from HWM | Worst day | Notional cap binds | Verdict |
|---|---|---|---|---|---|---|
| 1.0× | 0.75% | −5.23% | 5.86% | −1.69% | 0 | comp-safe, loses |
| 1.0× | 1.0% | −6.89% | 7.73% | −2.25% | 2× | comp-safe, loses |
| 1.0× | 1.5% | −9.26% | **10.50%** | −3.25% | 16× | **NOT SAFE** |
| 2.0× | 0.75–1.5% | −0.06% … −0.11% | 1.4–2.8% | ≤−1.63% | 0 | comp-safe, breakeven |
| 3.5× | 0.75% | +0.33% | 0.78% | −0.78% | 0 | comp-safe |
| 3.5× | 1.0% | +0.44% | 1.04% | −1.04% | 0 | comp-safe |
| 3.5× | 1.5% | **+0.66%** | 1.55% | −1.55% | 0 | comp-safe |

## Findings (honest read)

1. **The brief's core question ("how many winners get cut?") turned out
   not to be the binding constraint.** At 3.5×ATR the answer is
   excellent — 16 of 17 winners preserved, only the hostage cut. The edge
   still dies, because of point 2.
2. **The binding constraint is the first-profit exit's R-economics.**
   Wins exit at the first profitable close: +0.09R average against a
   3.5×ATR stop, +0.14R against 2.0×. Fifteen or sixteen tiny wins cannot
   carry even one or two −1R stop-outs at meaningful risk sizing. The
   design is a loss machine tight (−6.98R), a breakeven machine medium
   (−0.07R), and a rounding error wide (+0.44R ≈ +0.66% of capital per
   2.3 YEARS at the most aggressive comp-safe cell).
3. **What this proves about the original Track 4 "edge":** it lived
   entirely in the unbounded hold — the willingness to sit −16.5%
   underwater until rescue. Bound that risk in any way and the remaining
   per-trade profits are too small to matter. This is the cleanest
   possible demonstration that the no-stop design's returns were
   compensation for its uncapped tail, not a free lunch.
4. **No forward-test candidate is named.** Best comp-safe cell
   (3.5×/1.5%: +0.66%, maxDD 1.55%) is positive but economically
   negligible — promoting it would be theater. If a comp-compliant
   dip-buy is ever to exist, the EXIT must be rebuilt around R-meaningful
   targets against the stop (an R:R-gated design) — which is structurally
   the live 4h/1h trend engine's class, already built, corrected basis
   +2.86R. The circle closes: the comp-compliant version of "buy the dip
   with a stop and a real target" already exists in this repo.

## Reproduce

```powershell
python scripts/track4_mean_reversion.py --phase run --long-only --bias-tfs 12h --sma-windows 30 `
  --thresholds 1.25 --exit-modes first_profit --caps none --stop-atr-mult {1.0|2.0|3.5} --tag r4c_stopXX
```

Outputs: `research/output/track4_results_r4c_stop{10,20,35}.json`.
