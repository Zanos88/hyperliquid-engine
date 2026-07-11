# Study 1 — Breakout-Continuation, No Stop

Run 2026-07-11. **Verdict up front: this is Track 4 rediscovered under a
different (and worse) entry signal — NOT a new mechanism.** The no-stop
breakout's MAE/time-to-revert distribution is the same shape as Track 4's
−1.25 mean-reversion cell, only with *deeper* drawdowns and *longer* holds,
because the breakout buys higher into the same mean-reverting market. The
brief's stated concern is confirmed by the data. Backtest only; SIMULATED
(idealized fills; no slippage/funding). Zero Bullphoric reuse.

## Design

Identical breakout ENTRY to `docs/BREAKOUT_CONTINUATION.md` (fresh close-
break of the most recent confirmed swing level via `detect_swings`, 4H-bias
aligned, volume-confirmed) — **stop removed entirely; exit = hold until
first profitable close** (Track 4's original no-stop philosophy, not the
first-profit-WITH-stop design that failed in the two prior studies). No
leverage, fixed % of capital. MAE-before-profit tracked identically to
Track 4 so the two distributions are directly comparable. Entry axes swept:
bias {SMA, Fib/S-R} × TF {15m, 1H} × vol_mult {1.5, 2, 3}.

## The load-bearing comparison (the honesty check the brief demanded)

| Distribution | n | worst MAE | median MAE | share MAE ≤ −5% | TTR med / p90 / max (days) |
|---|---|---|---|---|---|
| **Track 4 −1.25** (fade the dip, no stop) | 17 | −16.5% | −0.85% | 0.06 | 0.5 / 2.7 / 23.3 |
| **This study, 1H pooled** (chase the break, no stop) | 175 | **−25.8%** | −0.67% | 0.11 | 0.08 / 3.3 / **65.9** |

**Same shape, worse tail.** Both: ~100% win rate by construction; a tiny
median drawdown (most trades barely dip before recovering); a small
minority of deep-underwater hostages; near-instant median resolution with
a long right tail. The mechanism is identical — *hold through the whipsaw
until it resolves favorably* — and the breakout entry is the worse of the
two triggers: it enters higher (after the break), so when the ~60% of
breakouts that fail revert, they drag the position deeper (−25.8% vs
−16.5% worst) and hold it longer (66d vs 23d max) than simply fading the
dip would have.

## Per-cell results

| bias | TF | vx | n | net P&L (% notional) | worst MAE | MAE≤−5% | TTR med/p90/max (d) |
|---|---|---|---|---|---|---|---|
| SMA | 1H | 1.5 | 37 | +9.64% | −25.3% | 0.11 | 0.08 / 2.5 / 63.8 |
| SMA | 1H | 2.0 | 25 | +4.02% | −25.8% | 0.16 | 0.08 / 4.9 / 65.9 |
| SMA | 1H | 3.0 | 26 | +3.91% | −25.8% | 0.12 | 0.29 / 4.1 / 65.9 |
| Fib/S-R | 1H | 1.5 | 38 | +6.68% | −16.0% | 0.08 | 0.08 / 3.3 / 41.9 |
| Fib/S-R | 1H | 2.0 | 30 | +1.72% | −16.0% | 0.10 | 0.08 / 2.8 / 41.9 |
| Fib/S-R | 1H | 3.0 | 19 | −2.52% | −11.1% | 0.11 | 0.08 / 4.1 / 23.2 |
| SMA | 15m† | 3.0 | 30 | +7.54% | −2.4% | 0.00 | 0.03 / 1.0 / 1.2 |
| Fib/S-R | 15m† | 3.0 | 16 | +6.08% | −2.6% | 0.00 | 0.03 / 0.7 / 1.1 |

† 15m = ~52 days, under-powered — the shallow-MAE, fast-resolve numbers are
a short calm-window artifact, not a distinct regime; not a basis for
conclusions. Full 12-cell table in the JSON.

## Findings (honest read)

1. **Track 4 rediscovered, not a new finding — state it plainly (per the
   brief).** Removing the stop from a continuation trade in a market that
   reverts 58–68% of the time at the breakout point does not produce a
   "continuation strategy." It produces a hold-through-whipsaw trade whose
   drawdown and recovery-time distribution is the same phenomenon as Track
   4's mean-reversion — the brief's up-front concern, confirmed.
2. **And it's the inferior entry.** Fading the dip (Track 4) enters lower
   and reverts shallower/faster; chasing the break enters higher and, on
   the majority that fail, reverts deeper and slower. If the no-stop
   hold-until-profit family is worth anything, the −1.25 dip entry
   dominates the breakout entry on every tail metric.
3. **The apparent positive returns are the same regime property, not an
   edge.** Positive net P&L on several 1H cells is the identical artifact
   flagged for Track 4: every 2024–26 dip/whipsaw eventually bounced. One
   non-bouncing leg — unbounded by design, and here up to 66 days and
   −25.8% underwater — converts it to a large loss.
4. **No new forward-test candidate.** Nothing here supersedes Track 4's
   −1.25 cell; it is a worse-entry version of the same trade.

## Reproduce

```powershell
python scripts/breakout_continuation.py --phase selfcheck
python scripts/breakout_continuation.py --phase run-nostop
```

Machine-readable: `research/output/continuation_no_stop.json` (12 cells +
pooled-1H distribution).
