# Backtest results — 2026-07-08 (SIMULATED, not live performance)

First runs of the walk-forward harness (`backtest.py`), replaying Hyperliquid
history through the **exact live strategy code** (`strategy/signals.py` —
same confluence, edge-trigger alignment, nearest-structure levels, R:R ≥ 2
gate as `main.py`). All runs stored in Supabase `backtest_runs` /
`backtest_trades` for later analysis.

## Simulation model (read before trusting any number)

- Idealized touch fills at exact entry/stop/target prices — no slippage.
- Ambiguous candles (both stop and target touched) count as **stop-first**
  (conservative).
- Taker fees 0.075% per side; **no funding** modeled.
- Window limited to Hyperliquid's 5,000-candle retention per timeframe
  (~208 days at 1h trigger).
- One position at a time; signals during an open position are skipped.
- No lookahead: bias slice contains only bias candles closed at/before the
  trigger close (unit-tested).

## Runs

| run_id | combo | indicators | window | trades | W/L | net R | PF | max DD | suppressed (R:R) |
|---|---|---|---|---|---|---|---|---|---|
| 01KX05QMPB… | 4h/1h | bias_sr+fisher+obv (default) | 2025-12-11 → 2026-07-08 | 6 | 2/4 | **−1.88R** | 0.72 | 4.78R | 92 |
| 01KX05RSMD… | 4h/1h | default+rsi | same | 6 | 2/4 | −1.88R | 0.72 | 4.78R | 82 |
| 01KX05S3YB… | 4h/1h | all 5 (+ichimoku) | same | 2 | 0/2 | −3.68R | 0.0 | 3.68R | 44 |
| 01KX05SD3X… | 15m/5m | default | 2026-06-20 → 2026-07-08 | 0 | — | — | — | — | 94 |

## Per-trade detail (default 4h/1h run)

| entry (UTC) | dir | entry | stop | target | exit | net R | bars |
|---|---|---|---|---|---|---|---|
| 2026-01-19 23:00 | SHORT | 92,497 | 92,644 | 91,800 | stop | −1.95 | 1 |
| 2026-03-19 12:00 | SHORT | 69,896 | 70,172 | 69,250 | target | +1.96 | 1 |
| 2026-03-20 00:00 | SHORT | 69,919 | 70,172 | 69,250 | stop | −1.42 | 1 |
| 2026-04-30 05:00 | SHORT | 75,457 | 75,612 | 74,894 | stop | −1.73 | 1 |
| 2026-05-15 08:00 | LONG | 80,782 | 80,590 | 81,223 | stop | −1.63 | 1 |
| 2026-05-24 23:00 | LONG | 76,759 | 76,585 | 77,375 | target | +2.88 | 4 |

## Findings (honest read)

1. **Sample far too small for statistical conclusions.** 6 trades in ~7
   months. Win rate / PF / net R here are noise, not signal. Do NOT treat
   −1.88R as "the strategy loses 1.88R" — treat it as "no evidence of edge
   yet, and two structural problems visible below."

2. **Structural problem A — stops are inside 1-hour noise.** 5 of 6 trades
   resolved within a single 1h bar. Nearest-structure stop distances came
   out at 0.15–0.35% of price (e.g. 147 pts on a $92.5k entry), which a
   normal 1h BTC candle traverses routinely. The ±0.15% structure buffer is
   too small for a 1h trigger timeframe.

3. **Structural problem B — fees consume 0.4–0.95R per trade.** Fee cost
   is `(entry+exit) × 0.075% ÷ stop distance`. With stops this tight, the
   0.15% round-trip taker fee is a huge fraction of one R: the 2026-01-19
   stop-out lost −1.95R (fees ≈ 0.95R on their own). At ~0.5R average fee
   drag, breakeven win rate at 2:1 gross rises from ~33% to ~50%. **This is
   true regardless of sample size** — it is arithmetic, not statistics.

4. **The R:R ≥ 2 gate is the dominant filter**: 92 alignments suppressed vs
   6 taken. Nearest-structure geometry rarely offers 2:1 — consistent with
   the forward test's quiet channel.

5. **Adding RSI changed nothing** (identical 6 trades — RSI only removed
   10 candidate alignments already failing R:R). **All-5 indicators** cut
   trades to 2 (both losses) — more confluence ≠ better here, it mostly
   just reduced the sample.

6. **15m/5m produced zero takes** in its 18-day window (94 suppressed) —
   structure levels on fast timeframes are even tighter relative to fees.

## Candidate next experiments (not yet run — user to prioritize)

- **Minimum stop distance** (e.g. ATR-based or ≥0.5% of price) so fees are
  a small fraction of R; re-run and compare stored runs.
- **Wider structure buffer** than ±0.15% for stop placement.
- **Maker-style limit entries** in simulation (fee model 0.02–0.045%) to
  quantify how much of the drag is fee-class-dependent.
- Longer trigger TFs (4h trigger / 1d bias) — wider natural stops, fewer
  1-bar resolutions; retention gives ~2.3 years of 4h candles.

Reproduce any run: `railway run --service btc-signal-bot python backtest.py
--bias-tf 4h --trigger-tf 1h --indicators default` (add `--no-store` for a
dry run). Every stored trade carries its `indicators_snapshot` for later
AI review.
