# Trend Dry-Run Forward Test — Protocol

Inception: 2026-07-09 (first marked bar: 1D close 2026-07-08 23:59:59 UTC).
Status: **RUNNING — paper only.** Follows docs/STRATEGY_TOURNAMENT.md §10
(rounds 3–4: trend beat buy-and-hold in 21/21 cells with ~half the drawdown
but below the in-sample luck bar → forward test is the agreed instrument).

> **PAPER ONLY.** No order dispatch, no arming switches, no interaction with
> the live engine's state. This process writes exactly one table
> (`trend_forward_marks`) and must NEVER write `portfolio_telemetry` /
> `trade_execution_ledger` / `engine_state` / `strategy_settings` /
> `risk_params` — the floor-guard trigger reads `portfolio_telemetry`'s
> latest row unfiltered, so a paper row there would change live entry
> validation (see the comment block at the end of db/schema.sql).

## Tracks (pre-registered from rounds 3/4 — no tuning since)

| Track | Rule | Role |
|---|---|---|
| tsmom30 | long while close > close 30 daily bars ago, else flat | primary (top Sharpe in both tournaments) |
| sma50 | long while close > SMA(50), else flat | shadow (second family) |
| buy_hold | always long (one inception fee) | benchmark |

BTC 1D, $100,000 paper equity per track, taker fee 0.075% per side on every
position change. Marking convention identical to the tournaments: the
position decided at the close of bar j earns bar j+1's log return; the fee
lands on the flip bar. Positions are recomputed deterministically from
candle history each tick, so marks are reproducible and restarts are exact.

## Mechanics

- `forward_test.py --once`: fetches the last 300 closed 1D bars
  (Hyperliquid, closed bars only), writes one mark per track per
  unprocessed bar into `trend_forward_marks`
  (`UNIQUE (strategy, bar_open_time_ms)` + `ON CONFLICT DO NOTHING`).
  Idempotent; overlapping or repeated runs are no-ops; downtime up to ~270
  days self-heals on the next run. `--report` prints the state read-only.
- Telegram (live channel, existing bot): position flips post audibly,
  prefixed `[TREND-FWD paper]`; inception was silent; buy_hold never
  alerts. Expected flip cadence from the tournaments: ~2–4/month per track.
- Scheduling (local, per user decision — no new cloud infrastructure):
  Windows Task Scheduler task **`btc-trend-forward-tick`** runs
  `scripts/trend_forward_tick.cmd` (which calls
  `railway run --service btc-signal-bot python forward_test.py --once`,
  logging to `%LOCALAPPDATA%\btc-trend-forward\tick.log`) at **10:30 and
  20:30 local daily plus at logon**, with missed-start catch-up. Two daily
  triggers + logon + self-healing make DST/UTC drift and laptop-off periods
  irrelevant.
- Why not inside the live engine: modifying `main.py` requires a redeploy
  that restarts the worker and wipes the V2 forward test's in-memory paper
  day; no other service is running to piggyback on; and physical
  separation is what guarantees the floor-guard contamination class can't
  happen. Upgrade path if local uptime proves insufficient: a 4th Railway
  service running `python forward_test.py --loop` (runbook pattern:
  same repo, custom start command) — the code already supports it.

## Review gate (pre-registered — no promotion decision before this)

Evaluate only when BOTH hold: **≥ 180 days elapsed AND ≥ 10 tsmom30
flips.** Criteria at review: tsmom30 net > 0 AND Sharpe (from daily marks)
≥ buy_hold's on the same marks. sma50 is contextual evidence, not a
selection candidate (no picking the better track after the fact — that
re-introduces the selection bias this program exists to avoid). Promotion
to anything beyond paper is a separate, user-gated decision per the
runbook's two-switch discipline. Early peeking at `--report` is expected
and harmless; early *decisions* are the thing the gate forbids.

## Inception state (2026-07-09)

| Track | Position at inception | Equity |
|---|---|---|
| tsmom30 | FLAT (close ≤ close 30d ago) | $100,000.00 |
| sma50 | FLAT (close ≤ SMA50) | $100,000.00 |
| buy_hold | LONG | $99,925.03 (entry fee) |

Both trend tracks starting FLAT is the system working: the current tape is
below both trend thresholds. First flips will come from the data.

## Ops

```powershell
python forward_test.py --report                     # local, read-only (needs DATABASE_URL)
railway run --service btc-signal-bot python forward_test.py --report
Get-Content "$env:LOCALAPPDATA\btc-trend-forward\tick.log" -Tail 20
Get-ScheduledTask btc-trend-forward-tick | Get-ScheduledTaskInfo
```
