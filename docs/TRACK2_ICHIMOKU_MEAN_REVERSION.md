# Track 2 — Ichimoku E2E Counter-Trend Module (experimental, standalone, backtest-only)

Build date: 2026-07-09. A SECOND, independent signal path
(`strategy/counter_trend.py`) that does not import or modify the trend
system (`strategy/signals.py`) and is never wired into the live/dry-run
engine. Built in an isolated `track2` git worktree (hygiene fix — see
below), full suite green before every commit.

## Research Findings

### Source-document verdicts (locked — do not re-open)

From `BTC_Ichimoku_Mean_Reversion_System.md`:

**REJECTED (never cite anywhere):** Section 8 architecture (Dual-Chamber
sandbox, Jito-MEV broadcast, NUC thread-pinning) and the
`social_sentiment_score`/`market_vector` schema columns — copy-pasted
from unrelated earlier docs. Section 7's Sharpe/win-rate/PF table — the
doc itself labels it "unverified in peer-reviewed literature". The
"Aetheris v2" 10/30/60/30 periods — superseded by the locked standard
periods.

**ADOPTED (sound independent of the above):** the E2E entry/exit
definition (TK cross precedes, mandatory full-candle close inside the
Kumo, dynamic opposite-edge target, ATR+fractal-swing stop); OBV regular
divergence + volume-momentum (LRS) flattening; the three
conflict-resolution architectures — recorded for Part 4, NOT built.

### Locked definitions (Zane's rules)

Ichimoku standard 9/26/52, displacement 26 (no crypto variant). E2E:
TK cross precedes; entry confirmed only on a full candle **close** inside
the cloud (wick rejected); target = opposite cloud edge, recomputed each
bar. OBV: regular divergence (OBV trend disagrees with price trend).

### Correction: Part 1's module already existed

`strategy/ichimoku.py` was built earlier (the confluence-indicator work)
with exactly the locked standard periods, displacement, and cloud-edge
exposure, and is unit-tested. So Part 1 REUSES it — a one-function
helper `ichimoku_components()` surfaces (tenkan, kijun, cloud_top,
cloud_bottom) — rather than duplicating a module.

### Key finding: exhaustion PRECEDES the reclaim (why the naive spec fires ~0)

An end-to-end funnel diagnostic on 4h/1h (run before shipping) exposed a
temporal inconsistency in the literal spec. Of 4,960 trigger bars, 73
have the full E2E geometry (a bullish TK cross within the recent window,
price having been below the cloud, and the candle closing back inside
the Kumo). But:
- Gating Fisher at the **entry bar** matched **0 of 73** — by the time
  price reclaims the cloud, the oversold Fisher extreme (which occurs at
  the low, ~10-15 bars earlier) has already passed.
- Widening to a 15-bar exhaustion window recovered 19 of 73.
- OBV **regular divergence** ("price lower now AND OBV higher") then
  matched **0 of those 19** — at a reclaim, price has already turned up,
  so "price lower now" is false.

Interpretation: the exhaustion gates describe the pre-reversal down-leg,
but the entry fires post-reversal. Two principled consequences, both
kept faithful to the spirit of the spec:
1. Both the TK cross and the Fisher exhaustion are checked as
   **preceding** the entry — the cross over a recent window, Fisher over
   a 15-bar exhaustion window (its min for longs / max for shorts), not
   the entry bar.
2. The OBV-divergence rule is left literal (anchored at the current bar)
   — so it genuinely rarely fires at a reclaim. This is exactly why the
   brief made `obv_rule` a sweep axis with `lrs_flattening` (momentum
   deceleration, direction-agnostic, no "price lower now" requirement)
   as the alternate. The sweep contrasts the two.

## Changes

- `strategy/ichimoku.py`: `+ ichimoku_components()` helper (reuse, no
  duplication).
- `strategy/counter_trend.py` (NEW): E2E detector. Reuses
  `bias_4h.detect_swings`/`horizontal_sr` (structure), `atr.wilder_atr`
  (stop), `trigger_1h.fisher_transform`/`on_balance_volume`. Returns a
  `CounterTrendSignal` (own type). Deterministic; `fisher_recent_min/max`
  supplied by the caller so `fisher_tf` stays a sweep axis.
- `backtest.py`: `--strategy counter_trend` single run + a
  `strategy: counter_trend` sweep path; dedicated
  `simulate_counter_trend_outcome` (fixed ATR stop, DYNAMIC
  opposite-cloud target recomputed each bar, stop-first, 0.075%/side
  fees, no-lookahead).
- `db/schema.sql`: `backtest_runs.strategy_type` (idempotent, default
  `'trend'`); counter-trend runs tag `'counter_trend'`.
- `sweep_counter_trend.yaml` (NEW): the 12-run grid.

## Repo structure (delta)

```
strategy/ichimoku.py            MOD  + ichimoku_components helper
strategy/counter_trend.py       NEW  E2E counter-trend detector
backtest.py                     MOD  counter-trend run/sweep + dynamic-target sim
db/schema.sql                   MOD  backtest_runs.strategy_type
sweep_counter_trend.yaml        NEW  12-run grid
tests/test_counter_trend.py     NEW  detector gates
tests/test_counter_trend_backtest.py NEW  dynamic-target sim
tests/test_indicators.py        MOD  ichimoku_components tests
main.py / strategy/signals.py / ledger / risk / live engine  UNTOUCHED
```

## Sweep design

Fixed 4h-bias / 1h-trigger (4h → structural S/R + fractal swings, 1h →
E2E cloud/TK/OBV — the live split, so counter-trend rows sit beside the
trend runs in `backtest_runs` for comparison). Axes: `fisher_tf`
{1h, 4h} × `obv_rule` {divergence, lrs_flattening} ×
`exhaustion_threshold` {1.5, 2.0, 2.5} = 12 runs. `fisher_tf` is a real
open question (the E2E pattern is 1h; the original exhaustion insight was
4h) — swept, not assumed.

## Comparison Table (SIMULATED — not live performance)

Run 2026-07-09, `sweep_id=01KX25W0YFGKH0VJK7VR25JE3S`, 12 runs stored in
`backtest_runs`/`backtest_trades` (`strategy_type='counter_trend'`),
window 2025-12-12 → 2026-07-08 (~208d, 4h/1h).

| fisher_tf | obv_rule | exh | trades | W-L | net R | PF | maxDD |
|---|---|---|---|---|---|---|---|
| 1h | divergence | 1.5 | 1 | 1-0 | +0.46 | — | 0.00 |
| 1h | divergence | 2.0 | 1 | 1-0 | +0.46 | — | 0.00 |
| 1h | divergence | 2.5 | 0 | — | — | — | — |
| 1h | lrs_flattening | 1.5 | 14 | 7-7 | −1.13 | 0.71 | 2.62 |
| 1h | lrs_flattening | 2.0 | 10 | 5-5 | +0.78 | 1.48 | 1.55 |
| 1h | lrs_flattening | 2.5 | 9 | 5-4 | +0.82 | 1.52 | 1.55 |
| 4h | divergence | 1.5 | 2 | 1-1 | +0.19 | 1.69 | 0.27 |
| 4h | divergence | 2.0 | 2 | 1-1 | +0.19 | 1.69 | 0.27 |
| 4h | divergence | 2.5 | 2 | 1-1 | +0.19 | 1.69 | 0.27 |
| 4h | lrs_flattening | 1.5 | 26 | 12-14 | −3.42 | 0.50 | 4.76 |
| 4h | lrs_flattening | 2.0 | 25 | 12-13 | −3.37 | 0.50 | 4.72 |
| 4h | lrs_flattening | 2.5 | 24 | 12-12 | −3.10 | 0.50 | 4.68 |

### Findings (honest read — n tiny throughout; nothing is an edge claim)

1. **`divergence` fires almost never (0-2 trades)** — as the funnel
   predicted: at a reclaim, price has already turned up, so the
   "price lower now" leg of regular divergence is rarely satisfied. The
   handful that do fire are marginally positive, but n≤2 is noise.
2. **`lrs_flattening` is the only variant with a workable sample**
   (9-26 trades) because momentum-deceleration doesn't require
   "price lower now". Its results split by Fisher timeframe:
   - **fisher 1h**: mixed-to-positive (+0.78R / +0.82R at exh 2.0/2.5,
     PF ~1.5 over 9-10 trades; −1.13R at exh 1.5 where the looser gate
     admitted more/worse trades).
   - **fisher 4h**: consistently **negative** (−3.1 to −3.4R, PF 0.50,
     ~25 trades) across all thresholds.
   The 1h-vs-4h Fisher split is the clearest signal in the table — and
   it directly answers the brief's open question: on this data the
   exhaustion gate belongs on the **1h setup timeframe**, not 4h.
3. **Threshold barely matters within a variant** — 1.5/2.0/2.5 move the
   count and R only modestly; not a sensitive knob here.
4. **Best in-sample cell**: fisher 1h + lrs_flattening + exh 2.5
   (+0.82R, PF 1.52, 5-4 over 9 trades). Promising *direction* only —
   9 trades over 7 months is nowhere near an edge claim, and PF ~1.5 at
   n=9 is well within noise.
5. **The divergence rule as literally specced is effectively unusable
   for entry-on-reclaim** (open item 3) — a future re-anchoring to the
   pre-reversal down-leg is the honest next experiment if this module is
   pursued.

Every number is SIMULATED (idealized touch fills, no slippage/funding,
stop-first ambiguity, taker 0.075%/side, 5,000-candle retention).

## vs the trend system

Trend system best in-sample cell (V2.3 Grid C, 4h/1h, SIMULATED):
fib_extension_preferred + structural — 9 trades, 4-5, +1.28R, PF 1.15.
Counter-trend numbers above are on the same 4h/1h window and the same
`backtest_runs` table (`strategy_type`), so they are directly comparable
— but n is tiny on both sides; neither is an edge claim.

## Part 4 — DEFERRED, not built

Integration between the trend and counter-trend systems (virtual
netting / regime-gated mutual exclusion / trend-priority scale-out) is
recorded in the brief and deliberately NOT implemented. `counter_trend.py`
imports nothing from `signals.py` and touches no live code.

## Hygiene (this session)

- The prior `railway up` deploy bundled the parallel staging session's
  then-uncommitted files; all were non-runtime (docs/tests/.env.example)
  and that session has since committed them. Nothing sensitive shipped;
  the engine runs only committed runtime code.
- Track 2 was built in an isolated `git worktree` (`track2` branch) to
  structurally prevent two concurrent sessions sharing a working tree —
  the class of risk behind that bundling.

## Git commits

1. `feat: ichimoku cloud-edge/TK helper for counter-trend (reuse existing module)`
2. `feat: E2E counter-trend signal module (isolated from trend strategy)`
3. `feat: counter-trend backtest integration + sweep axes (strategy_type tag)`
4. `docs: track 2 build doc + comparison table (vs trend system, same schema)`

## Open items

1. `fisher_tf` (1h vs 4h) — swept, results above; not pre-judged.
2. Exhaustion window (15 bars) and `cross_lookback` (6) are principled
   defaults chosen to fix the precede-timing, not tuned — a follow-up
   could sweep them if the module shows promise.
3. OBV-divergence anchoring: kept literal (fires rarely at reclaims); a
   future variant could measure divergence over the pre-reversal down-leg
   rather than ending at the entry bar. Flagged, not built.
4. Part 4 integration stays out of scope until both systems have real
   (larger-sample) results.
