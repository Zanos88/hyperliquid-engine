# Track 3 — 1D Bias + 4H Fisher Pullback-Entry & Exhaustion Cycling

Build date: 2026-07-09. Experimental, **backtest-only**, isolated from
the trend system (`strategy/signals.py`) and Track 2
(`strategy/counter_trend.py`) — never wired into the live/dry-run
engine. Local commits + local merge to master, not pushed (session
pattern).

## Context

Thesis: inside a favorable 1D structural bias, a 4H Fisher extreme
AGAINST the immediate move is a pullback entry (buy the dip in a bullish
1D bias), the opposite framing to Track 2's exhaustion-avoidance. Once
in, a favorable Fisher extreme (exhaustion in the trade's direction)
flips the leg to bank the pullback, cycling while the 1D bias holds.
This is a multi-leg state machine tracked as cumulative R across a whole
cycle (entry → eventual bias-flip flatten), not discrete R:R-gated bets
— so it needs its own module + simulator (as Track 2 did).

## Locked decisions

- **Ichimoku/Fisher settings**: standard (the 4H Fisher uses the
  existing period-10 `fisher_transform`); threshold 2.0, swept 1.5/2.5.
- **Stop = flat-and-rearm** (user decision, overriding the source
  brief's literal "stop → flip"): a stop-out is the leg being
  invalidated, NOT a reversal signal — so a stopped leg goes FLAT and
  the cycle re-arms via the normal pullback entry while the 1D macro
  bias still holds (earliest re-entry the NEXT bar — no same-bar churn).
  A short is only ever reached via the exhaustion FLIP from a long,
  never opened fresh in a bullish cycle. Mirror for bearish.
- **Every leg carries an ATR hard stop** (`strategy/atr.wilder_atr`,
  multiplier swept 1.0/1.5) — the non-negotiable cap on the failure mode
  where a trend pins Fisher extended and the reset never comes.
- **No per-leg R:R≥2 gate** — deliberate design difference from the
  trend system (repeated legs within one macro thesis, not independent
  bets); performance unit is per-cycle cumulative R.
- 1D bias flip away from the cycle direction (incl. → NEUTRAL) →
  immediate force-flatten, cycle ends.

## Two brief assumptions corrected by reading the code

1. **No bias generalization was needed.** `compute_bias`
   (`strategy/bias_4h.py`) already consumes any candle sequence, so 1D
   bias is just `compute_bias(daily_candles)` over a no-lookahead daily
   slice — no timeframe parameter, no duplicated logic
   (`strategy/fisher_cycle.daily_bias_at`).
2. **Part 3 needed a schema migration.** The `strategy_type` CHECK
   admitted only `('trend','counter_trend')` and would reject
   `'fisher_cycle'`. Widened idempotently (name-agnostic DROP + re-ADD);
   verified live.

## Changes

- `strategy/fisher_cycle.py` (NEW, isolated leaf): `daily_bias_at`;
  `CycleState`/`Leg`; `leg_stop` (reuse `wilder_atr`);
  `opening_direction` / `is_exhausted` / `macro_broken` pure helpers.
- `backtest.py`: `run_fisher_cycle_backtest` simulator (stop-first →
  flat-and-rearm, exhaustion flip, macro flatten, trailing-leg flush,
  per-cycle cumulative R); `--strategy fisher_cycle` single + sweep
  dispatch; per-leg fees; rows tagged `strategy_type='fisher_cycle'`.
- `db/schema.sql`: `strategy_type` CHECK widened to include
  `fisher_cycle`.
- `sweep_fisher_cycle.yaml`: 1D/4H × threshold {1.5,2.0,2.5} × atr_mult
  {1.0,1.5} = 6 runs.

## Sweep Comparison Table (SIMULATED — not live performance)

Run 2026-07-09, `sweep_id=01KX2HNGDX0K23WCBYWJ1729WC`, 6 runs stored in
`backtest_runs`/`backtest_trades` (`strategy_type='fisher_cycle'`),
window 2024-03-27 → 2026-07-09 (~2.3yr of 4H triggers; 1D bias back to
2020). "legs" = individual long/short legs; "cycles" = macro runs
(entry → bias-flip flatten), the performance unit; meanR = mean
cumulative net R per cycle.

| exh | atr_mult | cycles | legs | W-L (legs) | net R | PF | maxDD | mean cycle R |
|---|---|---|---|---|---|---|---|---|
| 1.5 | 1.0 | 78 | 157 | 51-106 | −10.29 | 0.90 | 33.12 | −0.132 |
| 1.5 | 1.5 | 78 | 143 | 57-86 | −4.13 | 0.94 | 21.03 | −0.053 |
| 2.0 | 1.0 | 68 | 128 | 45-83 | −2.11 | 0.97 | 19.05 | −0.031 |
| **2.0** | **1.5** | 68 | 119 | 48-71 | **+1.58** | **1.03** | 14.31 | **+0.023** |
| 2.5 | 1.0 | 59 | 111 | 38-73 | −6.16 | 0.92 | 22.68 | −0.104 |
| 2.5 | 1.5 | 59 | 102 | 41-61 | −0.97 | 0.98 | 15.24 | −0.017 |

## Findings (honest read)

1. **First track with a real sample — and the verdict is "no edge, ~
   breakeven-minus."** 102–157 legs / 59–78 cycles per run over 2.3
   years is far more than any prior track (trend: 6; counter-trend
   lrs: 9–26). PF sits at **0.90–1.03** — i.e. gross win/loss is
   essentially 1:1 and fees push most cells negative. Five of six runs
   lose; the one positive cell (exh 2.0 / atr 1.5, +1.58R, PF 1.03,
   +0.023 mean cycle R over 68 cycles) is statistically
   indistinguishable from zero. This is NOT an edge — it is a
   well-sampled null, which is a stronger, more useful result than the
   tiny-sample tracks.
2. **Wider ATR stops beat tighter ones, monotonically and on every
   threshold** (atr 1.5 > 1.0 in net R at 1.5/2.0/2.5: −4.13>−10.29,
   +1.58>−2.11, −0.97>−6.16) and roughly halve max drawdown (33→21,
   19→14, 23→15 R). The tight 1.0 stop is inside 4H noise — the same
   failure mode V2.2 found for the trend system's 1H stops, recurring
   here. If this module were pursued, atr_mult ≥ 1.5 is the floor.
3. **Threshold 2.0 is the least-bad** (best net at both stops), with
   2.5 worst at atr 1.0. Zane's stated 2.0 level holds up as the
   sensible centre; the brackets don't beat it.
4. **Low win rate (32–40%) offset by the flip mechanism**, not by
   winners running — cycles cumulate near zero. The exhaustion-flip
   banks small moves but the flat-and-rearm stops bleed on the legs
   that fail before a reset. Max drawdowns of 14–33R are large for a
   cumulative-R-near-zero system — a poor risk/reward profile even
   ignoring the negative expectancy.
5. **Flat-and-rearm did its job**: no pathological stop→flip
   knife-catching (that rule change vs. the source brief prevented a
   likely-worse result), and the ATR stop capped the trend-pinned-Fisher
   failure mode as intended — the losses are ordinary, not blow-ups.

Bottom line: the Fisher-cycle premise, tested on its own on 2.3 years of
BTC 4H, shows no edge — best case breakeven with large drawdowns. Every
number is SIMULATED (idealized touch fills, no slippage/funding,
stop-first ambiguity, taker 0.075%/side, 5,000-candle 4H retention);
real fills and funding would only worsen a PF already ≤ 1.03. No live
wiring; decision to pursue further or shelve is the user's.

## Git commits

1. `feat: 1D bias (reuse compute_bias, no-lookahead) - Track 3 Part 1`
2. `feat: fisher cycle state machine (isolated module) - Track 3 Part 2`
3. `feat: dedicated cycle simulator + 6-run sweep - Track 3 Part 3`
4. `docs: track 3 build doc + comparison table (real output only)`

## Open items

1. `exhaustion_threshold` and `atr_multiplier` are the swept axes;
   `fractal_width=2` / `sr_lookback=20` for the 1D bias are
   compute_bias's defaults, reused untuned (a follow-up could tune them
   for the daily timeframe if the module shows promise).
2. Part 4 (trend ↔ cycle integration: virtual netting / regime-gated
   exclusion / trend-priority scale-out) stays DEFERRED — not built,
   nothing toward it exists in the codebase.
3. Non-Fisher entry sources ("other correlation/indicator" as the cycle
   opener) deferred — the Fisher-cycle mechanism is tested on its own
   first.
