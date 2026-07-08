# V2.3 — Target Extension (Fib Extension + Blue-Sky), sweep-gated

Build date: 2026-07-09. Additive to V2.2 (hybrid stops, sweep harness,
Fisher-4H — all conclusions carried forward, not re-tested). All target
models are **backtest-only / default-off in the live engine** until the
Grid C results below are reviewed and a target model is explicitly
chosen (same rollout discipline as V2.2's stop models).

## Research Findings

### Why targets (V2.2's conclusion, carried forward)

V2.2's 90-run sweep was a decisive null with one robust finding: the
R:R>=2 gate against **nearest-structure targets** is the binding
constraint of the whole system — 0 trades in 2.3 years on 1d/4h even
with unmodified stops, 28–98 suppressions per cell everywhere. Hybrid
stops fixed fee drag but choked the gate (widening the denominator
without the numerator). This build widens the numerator.

Axes answered by V2.2 and deliberately NOT re-swept: indicator sets
(RSI no effect, all-5 hurts), Fisher-4H (entry filter blocked winners,
exit never fires at these hold times), hybrid@2.0 (behaviorally
identical to @1.5).

### What the code already had

`BiasResult.fib_levels` already computes extension levels — keys
`"1.272"`/`"1.618"`, direction-signed off the last confirmed swing
(`strategy/bias_4h.py`, `FIB_EXTENSIONS`). They were already in the
target candidate pool, but only ever chosen when they happened to be
the NEAREST level. V2.3 changes preference order, not level math.

### Deliberately deferred

Track 2 (Ichimoku/OBV mean-reversion): its target is also
nearest-structure-shaped — testing it before targets are fixed would
confound the two questions. Fix targets first.

## Changes

1. **`resolve_target()`** (`strategy/signals.py`), mirroring
   `resolve_stop()`:
   - `nearest_structure` (default) — byte-identical to prior behavior;
     the live engine passes nothing and is unchanged (locked by
     `test_default_call_target_unchanged`).
   - `fib_extension_preferred` — if a 1.272/1.618 extension lies beyond
     the nearest opposing level, prefer it (the farther of the two
     candidates), but cap at any structural S/R level sitting between
     them — never target through known structure.
   - `blue_sky_atr` — cumulative on fib_extension_preferred, plus
     `entry +/- 3.0 x ATR14(trigger TF)` when NO opposing level exists
     at all (price beyond all known reference levels). Returns None
     rather than guessing when ATR history is insufficient. Cumulative
     by design: model2-vs-1 isolates the extension effect, model3-vs-2
     isolates the blue-sky fallback.
   - R:R >= 2 gate and suppression logging unchanged — wider targets
     passing the gate more often is the mechanism under test, not a
     rule change. `reward_risk` is computed off the final resolved
     target via `Signal.target` (same single-source discipline as the
     V2.2 R-drift fix on stops).
2. **Sweep harness** (`backtest.py`): `target_model` +
   `blue_sky_atr_multiplier` flow through `run_backtest`,
   `expand_sweep`, single-run CLI, progress lines, comparison table,
   and `notes` JSON. No schema change.
3. **`sweep_config.yaml`** replaced with Grid C (Grids A/B are answered;
   configs remain in git history ec81c40/c0e91c4, results in the V2.2
   doc).

## Repo structure (delta)

```
strategy/signals.py         MOD  resolve_target + target_model params
backtest.py                 MOD  target axis through sweep + CLI
sweep_config.yaml           MOD  Grid C (27 runs) replaces answered A/B
tests/test_target_models.py NEW  9 tests
tests/test_backtest.py      MOD  target-axis expansion tests
docs/V2_3_TARGET_EXTENSION.md NEW this document
main.py / ledger / risk / db/schema.sql  UNTOUCHED
```

## Sweep design — Grid C

3 TF pairs ({4h/1h, 15m/5m, 1d/4h}) x 3 stop models ({structural,
hybrid@1.0, hybrid@1.5}) x 3 target models = **27 runs**, indicators
fixed at `default`, Fisher-4H off. Stop and target are crossed
deliberately — R:R couples them, so neither can be judged alone.
`blue_sky_atr_multiplier` fixed at 3.0 (unswept guess, open item 1).

## Grid C Comparison Table (SIMULATED — not live performance)

Run 2026-07-09, `sweep_id=01KX1730T6VN3PCERNP2AER8V7`, 27 runs stored in
`backtest_runs`/`backtest_trades`. Windows: 4h/1h 2025-12-12→2026-07-08
(~208d), 15m/5m ~17d, 1d/4h 2024-03-27→2026-07-08 (~2.3yr).

| tfs | stop | target | trades | W-L | net R | PF | maxDD | supp R:R |
|---|---|---|---|---|---|---|---|---|
| 4h/1h | structural | nearest (baseline) | 6 | 2-4 | −1.88 | 0.72 | 4.78 | 91 |
| 4h/1h | structural | **fib_ext** | **9** | **4-5** | **+1.28** | **1.15** | 6.77 | 87 |
| 4h/1h | structural | blue_sky@3.0 | 9 | 4-5 | +1.28 | 1.15 | 6.77 | 100 |
| 4h/1h | hybrid@1.0 | nearest | 1 | 1-0 | +1.61 | — | 0.00 | 96 |
| 4h/1h | hybrid@1.0 | **fib_ext** | **2** | **2-0** | **+4.49** | — | 0.00 | 93 |
| 4h/1h | hybrid@1.0 | blue_sky@3.0 | 2 | 2-0 | +4.49 | — | 0.00 | 106 |
| 4h/1h | hybrid@1.5 | nearest | 0 | — | — | — | — | 97 |
| 4h/1h | hybrid@1.5 | fib_ext | 1 | 1-0 | +2.01 | — | 0.00 | 95 |
| 4h/1h | hybrid@1.5 | blue_sky@3.0 | 1 | 1-0 | +2.01 | — | 0.00 | 108 |
| 15m/5m | structural | nearest | 0 | — | — | — | — | 94 |
| 15m/5m | structural | fib_ext / blue_sky | 2 | 0-2 | −3.18 | 0.00 | 3.18 | 92/97 |
| 15m/5m | hybrid@1.0 | fib_ext / blue_sky | 2 | 0-2 | −3.04 | 0.00 | 3.04 | 92/97 |
| 15m/5m | hybrid@1.5 | fib_ext / blue_sky | 1 | 0-1 | −1.42 | 0.00 | 1.42 | 93/98 |
| 1d/4h | structural | nearest | 0 | — | — | — | — | 58 |
| 1d/4h | structural | fib_ext / blue_sky | 4 | 0-4 | −5.38 | 0.00 | 5.38 | 53/54 |
| 1d/4h | hybrid@1.0 | fib_ext / blue_sky | 1 | 0-1 | −1.10 | 0.00 | 1.10 | 55/56 |
| 1d/4h | hybrid@1.5 | any | 0 | — | — | — | — | 58/59 |

(15m/5m and 1d/4h nearest-target rows: all zero trades under every stop
model, matching V2.2. fib_ext and blue_sky rows on those pairs are
identical to each other everywhere — collapsed for readability; full
27 rows in the DB under the sweep_id.)

## Findings (honest read)

1. **First positive cells in the whole program — and they line up.** On
   4h/1h, `fib_extension_preferred` beats `nearest_structure` on ALL
   THREE stop rows: structural −1.88R→+1.28R (PF 0.72→1.15, trades
   6→9), hybrid@1.0 +1.61R→+4.49R (2-0), hybrid@1.5 0 trades→+2.01R.
   The mechanism did exactly what it was designed to do: extension
   targets pass the R:R gate more often (supp 91→87) AND pay more per
   win (win rate rose 33%→44% despite farther targets — winners run to
   extensions instead of stalling at the first structure).
2. **Still not statistical proof.** The biggest cell is 9 trades; PF
   1.15 over 9 trades is a promising direction, not an edge claim. The
   consistency across stop models is the encouraging part, not any
   single number.
3. **Blue-sky added exactly nothing at 3.0x.** Identical results to
   fib_ext on every row; its only effect was +13 extra R:R-suppressed
   candidates on 4h/1h (targets at 3xATR vs their stops failed the
   gate). Honest nuance for open item 1: those 13 candidates exist — a
   larger multiplier might unlock some; untested.
4. **The edge, if real, is 4h/1h-shaped.** Extensions unlocked trades
   on 15m/5m (0-5 across cells) and 1d/4h (0-5) and they ALL lost —
   that is evidence against those pairs, not merely absence of trades.
   1d/4h going 0-4 over 2.3 years with extension targets is the
   clearest negative yet for the long-horizon pair.
5. **Candidate live configs this table supports (user's call, per
   locked constraint):** 4h/1h + fib_extension_preferred, with either
   structural stops (most flow: 9 trades/208d — best for forward-test
   data collection) or hybrid@1.0 (fewer, higher-quality: 2-0, zero fee
   bleed). The live engine remains on nearest_structure/structural
   until that decision is made explicitly.

Every number above is SIMULATED (idealized touch fills, no
slippage/funding, stop-first ambiguity, taker 0.075%/side, 5,000-candle
trigger retention).

## Git Commits

1. `feat: fib-extension + blue-sky target models (default unchanged)` (ab43394)
2. `feat: target-model sweep grid (27 runs, stop x target isolated)` (1d356fb)
3. `docs: v2.3 build doc + comparison table (real sweep output only)` (this commit)

## Open Items

1. `blue_sky_atr_multiplier` 3.0 is an unswept first guess — bracket it
   in a follow-up (mirroring V2.2's stop-multiplier bracket) only if
   Grid C shows blue_sky_atr is where the edge lives.
2. Live-default decision (which target model x stop model) is the
   user's call after reviewing this table — not automated, same as
   V2.2.
3. Staging Supabase project for the test suite (Supabase now Pro tier,
   2-project limit gone) — separate small task, flagged alongside this
   build; prevents a repeat of the 2026-07-08 live-engine-paused
   incident class.
4. Track 2 (Ichimoku/OBV mean-reversion) remains deferred until a
   target model is chosen.
