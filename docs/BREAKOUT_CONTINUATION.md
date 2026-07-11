# Breakout-Continuation — Key Levels + Volume, 15m/1H Trigger on 4H Trend

Run 2026-07-11, corrected-Fisher era (Fisher-independent). **Verdict up
front: NULL, and well-powered — 0 of 24 cells profitable at a meaningful
sample; the busiest cell (111 trades) loses; the two marginally-positive
cells are n ≤ 4 noise.** Trend-aligned, volume-confirmed breakouts of the
prior swing level, tight-stopped, do not show an edge on BTC at these
timeframes. Backtest only; SIMULATED (idealized stop/target fills — no
slippage/gap; 15m breakouts especially fill worse live, which would only
worsen these numbers). Zero Bullphoric reuse.

## Archetype & distinction

A genuinely third archetype: not trend-confluence (a breakout, not a
confluence entry) and not Track 4 (this CHASES the move, doesn't fade it,
and is deliberately tight-stopped — Track 4-Comp just proved a loose/no
stop was load-bearing for the fade's edge, so this inverts that).
**Entry fires ON the breakout bar's close** (aggressive chase, accept the
breakout price — NOT a retest/pullback entry). **No-lookahead:** swing
levels (fractals never repaint once formed), the 20-bar volume average,
and the 4H bias are all computed from data ≤ the trigger bar's close.

## Design (Zane's answers: "both" on all three open items)

- **Entry:** fresh close-cross above the most recent confirmed swing high
  (mirror below swing low), `detect_swings` reused (`fractal_width=2`), in
  the 4H-bias direction, with volume confirmation.
- **HTF bias (4H), both methods:** SMA (4H close > SMA50) and Fib/S-R
  (`compute_bias`). Long only when bias UP, short only when DOWN.
- **Volume, two measures:** conviction = bar volume ≥ mult × SMA(vol, 20),
  swept {1.5, 2, 3}; liquidity floor = fixed 20th-percentile of each TF's
  full volume distribution (**measured: 15m = 105.4, 1H = 484.3**), a gate.
- **Stop (principled tight):** just beyond the broken level ± 0.25×ATR14
  buffer — structurally the break's own invalidation, not an arbitrary
  distance. Loss ≈ −1R.
- **Target, both:** fixed 2R, and next-opposing structural level gated at
  R:R ≥ 2 (skips when no qualifying level — reported).
- **Trigger TF, both:** 1H (208d) and 15m (**only 52d — under-powered,
  flagged, no conclusions from its trade count**).
- Untuned defaults: SMA50, ATR14, vol-avg 20, buffer 0.25×ATR, one
  position at a time, fee 0.075%/side.

**24 cells** = bias {SMA, Fib/S-R} × TF {15m, 1H} × target {2R,
structural} × vol_mult {1.5, 2, 3}.

## Results (net R; **0 cells positive at n ≥ 20**)

| bias | TF | target | vx1.5 | vx2.0 | vx3.0 |
|---|---|---|---|---|---|
| SMA | 1H | 2R | −35.3 (n111) | −28.3 (n82) | −13.8 (n44) |
| SMA | 1H | struct | −2.4 (n9) | −2.4 (n4) | −2.7 (n2) |
| Fib/S-R | 1H | 2R | −6.6 (n65) | −4.1 (n51) | −6.9 (n23) |
| Fib/S-R | 1H | struct | +0.4 (n4) | −4.2 (n2) | 0 (n0) |
| SMA | 15m† | 2R | −73.6 (n98) | −39.0 (n68) | −2.2 (n28) |
| SMA | 15m† | struct | −12.3 (n11) | −7.6 (n5) | −2.6 (n3) |
| Fib/S-R | 15m† | 2R | −39.9 (n47) | −22.9 (n38) | −3.8 (n16) |
| Fib/S-R | 15m† | struct | −1.5 (n3) | −0.2 (n2) | +1.8 (n1) |

† 15m = ~52 days, under-powered — shown for completeness, not for
conclusions. The only two positive cells in the entire sweep are Fib/S-R
15m structural vx3 (**1 trade**) and Fib/S-R 1H structural vx1.5 (4 trades,
+0.42R) — both statistical noise.

## Why it fails: breakouts fall back through the level

Stop-out rate across every real-sample 2R cell is **58–68%** — the broken
level is re-crossed (false breakout) far more often than the move
continues:

| Cell | n | stop-outs | targets | stop-rate | PF |
|---|---|---|---|---|---|
| SMA 1H 2R vx1.5 | 111 | 71 | 40 | 64% | 0.65 |
| SMA 1H 2R vx2.0 | 82 | 54 | 28 | 66% | 0.62 |
| Fib/S-R 1H 2R vx1.5 | 65 | 38 | 27 | 58% | 0.87 |
| Fib/S-R 1H 2R vx2.0 | 51 | 30 | 21 | 59% | 0.90 |

A 2R target needs a ≈ 36% win rate (33% + fees) to break even; observed
win rates are 30–42% but the tight stop-just-beyond-the-level gets
whipsawed on the ~60% of breakouts that fail, so no cell reaches PF 1.

## Findings (honest read)

1. **Well-powered null — the strongest kind this program produces.**
   Unlike Track 4's tiny samples, breakout entries are frequent (44–111
   trades per 1H cell), so "no edge" here is a real, well-sampled result,
   not an absence of data. Trend-aligned, volume-confirmed breakouts of
   the recent swing high do not continue reliably enough to beat a tight
   stop on BTC at 15m/1H over these windows.
2. **Volume confirmation reduces losses but never flips the sign.** Higher
   vx monotonically cuts trade count and shrinks the loss (15m SMA 2R:
   −73.6R → −2.2R from vx1.5 → vx3), consistent with volume filtering some
   noise — but even vx3 stays net-negative everywhere with a real sample.
   Volume is a real filter, not a real edge.
3. **Fib/S-R bias beats SMA bias** (fewer false breakouts: 1H 2R vx2 PF
   0.90 vs 0.62) — structural bias is a better gate — but not enough to
   cross breakeven.
4. **The tight-stop finding is symmetric to Track 4-Comp.** There, a fade
   needed a loose/no stop to survive; here, a chase with a tight stop dies
   to whipsaw. Together they bracket the same structural fact: BTC's
   short-horizon moves mean-revert enough that neither a tight-stopped
   chase nor the profit-taking exit carries an edge — the R:R-gated
   trend-confluence engine (live, corrected basis +2.86R) remains the only
   structure in this program that has cleared its own tests.
5. **No forward-test candidate.** Nothing here is promotable.

## Reproduce

```powershell
python scripts/breakout_continuation.py --phase selfcheck
python scripts/breakout_continuation.py --phase run
```

Machine-readable: `research/output/breakout_continuation.json` (all 24
cells, per-trade detail).
