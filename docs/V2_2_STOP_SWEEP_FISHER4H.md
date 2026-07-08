# V2.2 — Hybrid Volatility Stops, Batch Backtest Sweep, 4H Fisher Exhaustion

Build date: 2026-07-08. Additive to V2.1 (severity tiers, TG dashboard,
web dashboard — untouched). All Fisher-4H mechanisms and the hybrid stop
are **backtest-only / config-off in the live engine** until the sweep
results below are reviewed (user decision 2026-07-08).

## Research Findings

### Source-document verdicts (locked — do not re-open)

From `BTC_Volatility_Stop-Loss_Research.md`:

**REJECTED (never cite anywhere — code comments, docs, alerts):**
- The "Academic and Quantitative Research Benchmarks" table. Verified
  against the actual arXiv 2604.27150 abstract: the cited Sharpe /
  ATR-multiple figures are not in the paper. Real citation, fabricated
  numbers.
- Citation [8] — broken `[unknown_url]` placeholder.
- The external BTC hourly log-return statistics table (no date range,
  no exchange). Replaced by `log_return_stats()` in `backtest.py`,
  which computes mean/stdev/excess-kurtosis from the exact Hyperliquid
  candles each run consumed and stores them in `backtest_runs.notes`.

**ADOPTED (verified sound independently):**
- Fee-drag arithmetic: fee_R = round-trip taker fee / stop distance.
  Matches this repo's own 2026-07-08 backtest observations (0.4–0.95R
  fee drag at 0.15–0.35% stops) exactly.
- Wilder's smoothed ATR (standard, correctly stated).
- Hybrid stop architecture: wider of (structural, ATR floor) — `min()`
  for longs, `max()` for shorts.
- R-Drift warning: size off the FINAL resolved stop distance, never the
  nominal structural distance.

### Fisher-4H exhaustion (user heuristic, now measurable)

|4H Fisher| >= 2.0 marks the move as exhausted — a **hard rule from the
user's live discretionary trading** (confirmed 2026-07-08). The sweep
brackets it with 1.5/2.5 as sensitivity checks. Two independent
mechanisms, both backtest-only:
- **entry filter** — don't chase: suppress a fresh signal when 4H
  Fisher is already extended in the same direction.
- **exit signal** — scale out: exit when 4H Fisher crosses INTO
  extended territory in the trade's favor (edge semantics; a position
  entered while already extended never exits on the pre-existing
  extension).

### Retention math (answers brief open item 3)

A "full ~2.3yr 4h/1h re-run" is impossible: the window is capped by the
TRIGGER timeframe's 5,000-candle Hyperliquid retention (1h -> ~208
days). 1d/4h (5,000 x 4h ≈ 833 days ≈ 2.3yr) is the only long-horizon
pair and is in the sweep.

## Changes

1. **Hybrid stop** (`strategy/atr.py`, `strategy/signals.py`):
   `resolve_stop()` picks the wider of the structural stop and
   `entry -/+ atr_multiplier * ATR14(trigger TF)`. The resolved value is
   set on the frozen `Signal.stop` and R:R is computed from it, so every
   downstream consumer (ledger sizing, risk recording, floor guard)
   automatically uses the final distance — the R-Drift fix is
   structural, not a patch at each call site. `risk/sizing.py` has no
   competing stop floor (verified), so there is exactly one source of
   stop distance. Live default remains `stop_model="structural"` —
   byte-identical behavior, locked by tests.
2. **Batch sweep harness** (`backtest.py --sweep sweep_config.yaml`):
   YAML-driven combo expansion; each unique timeframe fetched once per
   sweep (consistent windows); one stored `backtest_runs` row per combo
   with sweep metadata + real return stats in `notes` JSON (no schema
   change); ASCII progress lines + final comparison table. Single-run
   flags unchanged and verified to reproduce the 2026-07-08 baseline
   exactly (6 trades, 2W/4L, −1.88R, 92 suppressed).
3. **Fisher-4H exhaustion** (`strategy/signals.py`, `backtest.py`):
   entry filter runs AFTER the R:R gate so its suppression count
   isolates trades that would otherwise have been taken
   (`SuppressedSignal.kind="fisher4h_exhaustion"`); exit signal adds
   `exit_reason="fisher_exhaustion"` to the simulator (stop/target
   touches in the same bar take precedence — conservative). The 4H
   Fisher line is precomputed once per run (the construction is causal,
   so this is lookahead-safe) and bisect-indexed per trigger close; a
   dedicated 4h series is fetched regardless of the TF pair because the
   heuristic is specifically about the 4H chart.

Unchanged (locked constraints): R:R >= 2 gate, circuit breaker −2.5%,
static floor $94,000, daily floor day-start−$3,000, Propr-only
execution, strategy/risk/ledger module firewall, zero Bullphoric
sharing.

## Repo structure (delta)

```
strategy/atr.py            NEW  Wilder ATR-14 series
sweep_config.yaml          NEW  curated 90-run sweep (Grid A + Grid B)
tests/test_hybrid_stop.py  NEW  11 tests incl. R-drift regression
docs/V2_2_STOP_SWEEP_FISHER4H.md  NEW  this document
strategy/signals.py        MOD  resolve_stop, stop_model/fisher4h params
backtest.py                MOD  sweep mode, exhaustion exit, return stats
tests/test_backtest.py     MOD  +17 tests (sweep, stats, exhaustion)
main.py / ledger/tracker.py / risk/sizing.py / db/schema.sql  UNTOUCHED
```

## Sweep design

- **Grid A — stop models, Fisher off** (36 runs): {4h/1h, 15m/5m,
  1d/4h} x {default, default+rsi, all5} x {structural, hybrid@1.0,
  hybrid@1.5, hybrid@2.0}.
- **Grid B — Fisher-4H, default indicators** (54 runs): same TF pairs x
  {structural, hybrid@1.5} x {entry-only, exit-only, both} x thresholds
  {1.5, 2.0, 2.5}. Baselines are Grid A's default-indicator rows.
- Axis-isolated by design (user decision): ~6-trade cells make a full
  360-run cross uninterpretable; the full cross remains a YAML edit.

## Sweep Comparison Table (SIMULATED — not live performance)

Run 2026-07-08, `sweep_id=01KX0QMDYN284SNE277YSS9Z33`, 90 runs, all
stored in `backtest_runs`/`backtest_trades`. Windows: 4h/1h =
2025-12-12→2026-07-08 (~208d), 15m/5m = 2026-06-21→2026-07-08 (~17d),
1d/4h = 2024-03-27→2026-07-08 (~2.3yr trigger retention; 1d bias back
to 2020).

### Grid A — stop models (Fisher-4H off)

Every cell on **15m/5m and 1d/4h took ZERO trades** under every stop
model and indicator set (suppressed by the R:R gate: 42–95 per cell on
15m/5m, 28–58 on 1d/4h — including 0 trades in 2.3 YEARS on 1d/4h).
The 4h/1h rows:

| indicators | stop | trades | W-L | net R | PF | maxDD | supp R:R |
|---|---|---|---|---|---|---|---|
| default | structural | 6 | 2-4 | −1.88 | 0.72 | 4.78 | 92 |
| default | hybrid@1.0 | 1 | 1-0 | +1.61 | — | 0.00 | 97 |
| default | hybrid@1.5 | 0 | — | — | — | — | 98 |
| default | hybrid@2.0 | 0 | — | — | — | — | 98 |
| +rsi | structural | 6 | 2-4 | −1.88 | 0.72 | 4.78 | 82 |
| +rsi | hybrid@1.0 | 1 | 1-0 | +1.61 | — | 0.00 | 87 |
| +rsi | hybrid@1.5/2.0 | 0 | — | — | — | — | 88 |
| all 5 | structural | 2 | 0-2 | −3.68 | 0.00 | 3.68 | 44 |
| all 5 | hybrid@1.0 | 1 | 1-0 | +1.61 | — | 0.00 | 45 |
| all 5 | hybrid@1.5/2.0 | 0 | — | — | — | — | 46 |

### Grid B — Fisher-4H exhaustion (default indicators)

All 15m/5m and 1d/4h cells: zero trades (same R:R-gate suppression as
Grid A). All hybrid@1.5 cells: zero trades. The 4h/1h structural rows —
the only cells with trade flow:

| fisher4h | trades | W-L | net R | PF | maxDD | supp R:R | supp exh |
|---|---|---|---|---|---|---|---|
| off (baseline) | 6 | 2-4 | −1.88 | 0.72 | 4.78 | 92 | 0 |
| entry@1.5 | 2 | 0-2 | −3.36 | 0.00 | 3.36 | 92 | 4 |
| entry@2.0 | 3 | 0-3 | −5.31 | 0.00 | 5.31 | 92 | 3 |
| entry@2.5 | 4 | 1-3 | −2.43 | 0.54 | 5.31 | 92 | 2 |
| exit@1.5 | 6 | 2-4 | −1.88 | 0.72 | 4.78 | 92 | 0 |
| exit@2.0 | 6 | 2-4 | −1.88 | 0.72 | 4.78 | 92 | 0 |
| exit@2.5 | 6 | 2-4 | −3.95 | 0.41 | 4.78 | 92 | 0 |
| both@1.5 | 2 | 0-2 | −3.36 | 0.00 | 3.36 | 92 | 4 |
| both@2.0 | 3 | 0-3 | −5.31 | 0.00 | 5.31 | 92 | 3 |
| both@2.5 | 4 | 1-3 | −4.50 | 0.15 | 5.31 | 92 | 2 |

## Findings (honest read — n is tiny everywhere; suppression counts are the robust part)

1. **The R:R >= 2 gate against nearest-structure targets is the binding
   constraint of the whole system.** It suppressed 28–98 alignments per
   cell on every TF pair — including ZERO trades in 2.3 years on 1d/4h
   even with the current structural stops. This is not a stop-width
   problem alone: nearest-opposing-structure targets are simply too
   close to clear 2:1 very often, on any timeframe tested.
2. **Hybrid stops fix fee drag but starve the gate.** Widening the stop
   halves-or-worse the R:R against unchanged targets: hybrid@1.5/2.0
   took zero trades anywhere; hybrid@1.0 let exactly one trade through
   (won, +1.61R net — clean of the 0.4–0.95R fee bleed that plagued
   structural stops, which is precisely the mechanism working as
   intended, but n=1 proves nothing).
3. **Fisher-4H entry filter at 2.0 (the hard-rule level) made things
   worse in this sample**: it blocked 3 would-be entries but the trade
   set that remained went 0-3 (−5.31R) vs the baseline's 2-4 (−1.88R) —
   in this window the filter removed winners, not losers. (Blocking an
   entry also frees the one-position slot, so the downstream trade set
   shifts — counts don't subtract linearly.)
4. **Fisher-4H exit never fired at the 2.0 level** — trades resolve in
   1–4 trigger bars, faster than a 4H Fisher crossing can develop. The
   only variant that changed anything was exit@2.5 via the
   already-extended-at-entry edge case, and it cut the big winner short
   (−3.95R vs −1.88R). No evidence the exit helps at these hold times.
5. **What the data actually points at**: target selection. Stops can be
   made survivable (hybrid works mechanically) and fees manageable, but
   only if targets extend beyond the nearest opposing structure —
   the fib-extension / blue-sky logic previously discussed and
   deferred, or a re-examined R:R gate, are the levers this sweep
   isolates. Changing either is a strategy decision, not a code fix —
   user call.

Every number above is SIMULATED (idealized touch fills, no
slippage/funding, stop-first ambiguity, taker 0.075%/side). Full 90-row
raw table reproducible: `railway run --service btc-signal-bot python
backtest.py --sweep sweep_config.yaml` or query `backtest_runs WHERE
notes LIKE '%01KX0QMDYN284SNE277YSS9Z33%'`.

## Git Commits

1. `feat: hybrid ATR+structural stop, R-drift fix` (c43b8f1)
2. `feat: batch sweep harness (config-driven, 1d/4h TF pair added)` (ec81c40)
3. `feat: 4H Fisher exhaustion - entry filter + exit signal variants (backtest-only)` (c0e91c4)
4. `docs: v2.2 build doc + full sweep comparison table` (this commit)

## Open Items

1. `atr_multiplier` 1.0/1.5/2.0 and ATR period 14 are generic-convention
   defaults; the sweep IS the tuning pass — no claim of optimality.
2. Fisher-4H threshold 2.0 confirmed as a hard rule from the user's own
   trading; 1.5/2.5 results are sensitivity checks only.
3. Live wiring of any winning variant (hybrid stop config for the
   engine, exhaustion exit into `ledger/tracker.py`) is a separate,
   user-gated step after these results are reviewed. Note the
   structural tension the sweep quantifies: widening stops without
   touching the R:R >= 2 gate or target selection mechanically lowers
   R:R and suppresses more entries.
4. Out of scope (deferred by design): contrarian fade-the-exhaustion
   signal class — architecturally a new signal type, not a filter.
