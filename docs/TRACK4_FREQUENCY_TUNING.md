# Study 2 — Frequency/Trigger Tuning for Track 4 (Non-Comp Mean-Reversion)

Run 2026-07-11. **Verdict up front: faster triggers buy large frequency
gains but trade the edge away — no faster trigger is a forward-test
candidate.** Frequency scales 7.4 → 57.8 → 140 trades/year from 4H → 1H →
15m, but net P&L flips from +6.66% (4H) to negative (1H/15m), and a
window-controlled check confirms this is the trigger timeframe, not the
different data window. The −1.25 / **4H** cell stands alone. Backtest only;
SIMULATED (idealized fills, no slippage/funding). Reuses Track 4's
entry/exit logic with the entry timeframe parameterized.

## Design

**Fixed (Round 4 baseline):** 12H SMA30 bias, −1.25 Fisher threshold,
long-only, no stop, first-profit exit. **Varying — trigger timeframe only:**
4H (Round 4's original) vs 1H vs 15m Fisher. Prior art cited (Track 2's
fisher_tf axis found 1H > 4H for that *different* mechanism — a real reason
to test, not conclusive).

**Window confound, stated plainly:** the 5,000-bar retention cap means the
three triggers span different periods — 4H ≈ 833d (2024-03→2026-07), 1H ≈
208d (2025-12→), 15m ≈ 52d. Raw trade counts are therefore not comparable;
frequency is normalized to trades/year, and a same-window control (below)
isolates trigger-TF from period.

## Comparison table (centerpiece)

| Trigger | Window | Trades | **Trades/yr** | Wins | Net P&L (% notional) | Worst MAE | TTR med/p90/max (d) |
|---|---|---|---|---|---|---|---|
| **4H (baseline)** | 833d | 17 | **7.4** | 17/17 | **+6.66%** | −16.53% | 0.5 / 2.7 / 23.3 |
| 1H | 208d | 33 | **57.8** | 30/33 | **−2.10%** | −7.95% | 0.08 / 1.3 / 4.8 |
| 15m† | 52d | 20 | **139.9** | 19/20 | **−0.87%** | −4.28% | 0.04 / 0.4 / 0.5 |

† 15m = ~52 days, under-powered — shown for completeness.

### Window-controlled check (isolates TF from period)

| Trigger, same 208-day window | Trades | Trades/yr | Net P&L | Worst MAE |
|---|---|---|---|---|
| 4H (restricted to the 1H window) | 8 | 14.0 | **+3.07%** | −3.69% |
| 1H (native) | 33 | 57.8 | **−2.10%** | −7.95% |

On the **identical** 208 days, 4H stays positive (+3.07%) while 1H is
negative — so the edge difference is the trigger timeframe, not the window.
(4H's full-window +6.66% vs restricted +3.07% shows the earlier 2024–25
period was extra-favorable, but 4H stays positive in both.)

## Findings (honest read)

1. **Frequency is achievable — the edge is not.** A faster Fisher trigger
   fires 8× (1H) to 19× (15m) more often, decisively answering "can we
   increase frequency." But the 4H Fisher *extreme* carries mean-reversion
   information that the 1H and 15m extremes do not: net P&L degrades from
   +6.66% to −2.10% / −0.87%, and the window control proves this is the
   timeframe, not luck of period.
2. **"More frequent but worse" — the exact trade-off the brief asked to
   check.** Faster triggers do improve the tail (worst MAE −16.5% → −4.3%;
   max hold 23d → 0.5d — shallower, faster-resolving dips), but a shallow
   dip that resolves fast is one that barely moved: the per-trade edge net
   of the 0.15% round-trip fee vanishes. The 4H trigger's deeper, rarer
   extremes are where the reversion premium actually lives.
3. **Track 2's 1H > 4H hint did not transfer.** That was a different
   mechanism (Ichimoku E2E counter-trend); for this Fisher-dip design the
   relationship inverts — 4H > 1H > (15m). Testing rather than assuming
   was the right call.
4. **No faster trigger is a forward-test candidate.** The −1.25 / 4H cell
   remains the sole non-comp mean-reversion candidate; 1H/15m are
   dominated on the only metric that matters (net edge) despite winning on
   frequency and tail. Frequency for its own sake is not the goal.

## Reproduce

```powershell
python scripts/track4_mean_reversion.py --phase run-trigger
```

Machine-readable: `research/output/track4_trigger_tuning.json`. Frozen
inputs: `research/data/BTC_{4h,1h,15m}_snapshot.json` (15m frozen on first
run).
