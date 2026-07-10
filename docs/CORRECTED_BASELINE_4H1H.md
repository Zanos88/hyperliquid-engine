# Corrected Backtest Baseline — Live Config (4H/1H, structural stop, fib_extension target)

Date: 2026-07-10. Run: sweep `01KX5ANYYXR0CP14EGP9ZWC1XZ` (gate-off cell),
computed on **corrected Fisher** (fix `9da31ee` — the pre-fix indicator was
saturated, |F| ≥ 2 on ~45% of bars; see docs/FISHER_FIX_REVERIFICATION.md).
This supersedes V2.3 Grid C's +1.28R headline for the same config.

> **SIMULATED — not live performance.** Idealized touch fills, no
> slippage/funding, stop-first on ambiguous candles, taker 0.075%/side,
> window limited to the most recent 5,000 1H candles.

## Headline: old vs corrected

| | Buggy Fisher (V2.3 basis) | **Corrected Fisher** |
|---|---|---|
| Window | 2025-12-12 → 2026-07-09 | 2025-12-13 → 2026-07-10 (~209 days) |
| Trades | 9 | **8** |
| W–L | 4–5 | **4–4** |
| Net | +1.28R | **+2.86R** |
| Profit factor | 1.15 | **1.43** |
| Max drawdown | 6.77R | **3.72R** |
| Suppressed by R:R gate | 87 | 87 |

## Per-trade detail (corrected run, all 8 trades)

| # | Entry (UTC) | Dir | Entry | Stop | Target | R:R | Exit | Bars | Net R |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-01-08 03:59 | SHORT | 90,812 | 91,092 | 89,388 | 5.08 | stop | 1 | −1.49 |
| 2 | 2026-01-19 18:59 | SHORT | 93,011 | 93,506 | 91,800 | 2.45 | target | 11 | **+2.17** |
| 3 | 2026-03-17 23:59 | SHORT | 73,864 | 74,106 | 73,318 | 2.26 | stop | 2 | −1.46 |
| 4 | 2026-03-18 10:59 | SHORT | 73,906 | 74,106 | 73,318 | 2.94 | target | 1 | **+2.39** |
| 5 | 2026-03-19 11:59 | SHORT | 69,896 | 70,172 | 69,250 | 2.34 | target | 1 | **+1.96** |
| 6 | 2026-03-22 19:59 | SHORT | 68,160 | 68,263 | 67,720 | 4.26 | stop | 1 | −1.99 |
| 7 | 2026-04-30 04:59 | SHORT | 75,457 | 75,612 | 74,851 | 3.90 | stop | 1 | −1.73 |
| 8 | 2026-05-24 22:59 | LONG | 76,759 | 76,585 | 77,399 | 3.68 | target | 4 | **+3.01** |

Equity path (cumulative R): −1.49 → +0.68 → −0.78 → +1.61 → **+3.57 peak**
→ +1.58 → −0.15 trough → **+2.86**. Max drawdown 3.72R (peak-to-trough).

## What the fix actually changed (trade-by-trade reconciliation)

Six of the eight trades are identical to the buggy run — the fix changed
entry timing only at the margins, and the reconciliation is exact
(+1.28 − 1.42 loser − 1.63 loser removed, −1.46 loser added ⇒ +2.86):

- **Dropped (existed only under saturated Fisher): two losers.** The
  2026-03-19 23:59 SHORT (−1.42R) and the 2026-05-15 LONG (−1.63R) were
  entries whose Fisher "cross" was an artifact of the pegged indicator
  oscillating at the clamp. Correct Fisher never crossed there.
- **Added (missed by the saturated indicator): one loser.** The 2026-03-17
  23:59 SHORT (−1.46R) is a genuine cross the buggy series obscured.
- Net effect: **+1.58R and drawdown nearly halved**, entirely from cleaner
  entry timing — same stop model, same target model, same R:R gate, same
  confluence rules.

## Honest read

1. **This is the corrected basis for the live config, not proof of edge.**
   Eight trades over ~7 months is attribution-grade, not statistics; PF
   1.43 at n=8 can be luck. What it establishes is that the live config's
   backtest footing got *better*, not worse, when the indicator was fixed —
   the meaningful crosses filter entries more cleanly than saturated ones.
2. **Character of the window:** 7 of 8 trades are shorts (the window was
   predominantly downtrend/chop), exits are fast (6 of 8 resolve within
   2 bars), and losses cluster tightly around −1.5 to −2R (stops doing
   their job — no blow-ups). Pace ≈ 14 trades/yr, ~+5R/yr at this rate —
   descriptive extrapolation only.
3. **The dry-run forward test remains the arbiter.** This number describes
   the same 209 days the system already lived through, now measured with a
   working instrument. Go-forward evidence accrues from the live dry-run
   ledger (once the fix is deployed) and the trend forward test.
4. Reproduce: `railway run --service btc-signal-bot python backtest.py
   --sweep sweep_oi_gate.yaml` (gate-off 4h/1h cell) or single run:
   `python backtest.py --bias-tf 4h --trigger-tf 1h --target-model
   fib_extension_preferred --no-store` (window shifts with fetch time).
