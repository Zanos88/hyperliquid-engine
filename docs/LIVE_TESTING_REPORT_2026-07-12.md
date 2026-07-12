# Live Testing Status Report — 2026-07-12

Data pulled read-only from the LIVE Supabase project (`lnycymeylmhjqpwtdint`)
and local scheduled-task logs at **2026-07-12 ~10:20 UTC**. This is a dated
snapshot, not a standing dashboard — the reproduce commands at the bottom
regenerate it. Covers everything running LIVE (dry-run/paper); backtest
results are cited, not re-derived — see the linked docs.

## 1. Live trend engine (4H/1H, corrected Fisher)

Running since the Fisher fix deploy, **2026-07-10 06:47 UTC**
([FISHER_FIX_REVERIFICATION.md](FISHER_FIX_REVERIFICATION.md)).

| | |
|---|---|
| State | **ACTIVE**, DRY-RUN (both arming switches closed) |
| Bias | **NEUTRAL** ("below 0.618 retrace or lost support") |
| Fisher (1H, corrected) | +0.54 — sane, nowhere near the pre-fix saturation |
| Telemetry rows | 6,080 (first 2026-07-08 06:13 UTC, latest 2026-07-12 00:25 UTC) — flowing every ~60s, no gaps |
| Equity | **$100,000.00 unchanged across all 6,080 rows** |
| Signals generated (`pending_signals`) | **0, ever** |
| Trades (`trade_execution_ledger`) | **0, ever** |
| Risk events | 2 total, both benign `settings_change` rows from the 2026-07-08 V2.3 go-live (target_model → fib_extension_preferred); **0 since the Fisher fix** |
| Circuit-breaker halts | 0 |

No crashes, no InvalidToken loops, no repeated errors — the engine has been
quietly healthy since the fix. It has simply not seen a qualifying
confluence entry yet.

## 2. Trend forward test (4 paper tracks)

Protocol: [TREND_FORWARD_TEST.md](TREND_FORWARD_TEST.md). Inception
2026-07-08/09. Scheduled task `btc-trend-forward-tick`: last run
2026-07-11 20:30, result 0 (success), no missed runs.

| Track | Marks | Flips | Latest state | Net since inception |
|---|---|---|---|---|
| buy_hold | 3 | 1 (entry fee) | LONG, $102,928.41 | **+2.93%** |
| tsmom30 (primary) | 3 | 1 | LONG (flipped 2026-07-10), $101,394.86 | **+1.39%** |
| sma50 (shadow) | 3 | 0 | FLAT, $100,000.00 | 0.00% |
| track4_meanrev | 1 | 0 | FLAT, $100,000.00 | 0.00% (added 2026-07-11 — day 1) |

**Review gate** (pre-registered, no early decisions): tsmom30 needs
**≥180 days AND ≥10 flips**; track4_meanrev needs ≥180 days AND ≥10
completed trades. Elapsed so far: 3–4 days. Not remotely close — this
table is a health check, not an evaluation.

## 3. Order-book snapshot logger

Protocol: [ORDERBOOK_IMBALANCE_LAYER.md](ORDERBOOK_IMBALANCE_LAYER.md).

| | |
|---|---|
| Snapshots logged | **0** |
| Task last run | 2026-07-12 10:15:25, result 0 (success) |
| Task next run | 2026-07-12 11:00:45 |
| Last run's outcome | `off-boundary — skipped (929s past 2026-07-12 00:00:00 UTC; guard is 120s)` |

**Not an incident.** The task was registered a few minutes before this
report, mid-hour; its one run so far correctly hit the 120-second
contemporaneity guard and skipped rather than log a stale snapshot. It has
not yet reached a real hourly boundary (hh:00:45) since creation — the
first real snapshot is expected at 11:00:45 UTC today. Re-run `--report`
in ~24h to confirm the hourly cadence holds; laptop-sleep hours will show
as permanent gaps by design (the book is live-only, no backfill possible).

## 4. Interpretation

1. **Zero live trades in ~4 days is expected, not a fault.** The corrected
   4h/1h backtest paces roughly 14 trades/year on this config
   ([CORRECTED_BASELINE_4H1H.md](CORRECTED_BASELINE_4H1H.md): 8 trades
   over 209 days) — one entry every 3–4 weeks on average, with idle
   stretches longer than that. Four days of NEUTRAL bias is comfortably
   inside normal variance, not a sign anything is broken. This is the same
   frequency finding Grid E already quantified
   ([FEEDBACK_DD_FREQUENCY_REVIEW.md](FEEDBACK_DD_FREQUENCY_REVIEW.md)).
2. **sma50 flat for 4 days is correct behavior.** A 50-day SMA cannot move
   meaningfully in under a week of data; nothing to read into this yet.
3. **tsmom30 (+1.39%) trailing buy_hold (+2.93%) is trend-following's
   known lag cost, not underperformance.** tsmom30 entered the rally two
   days after buy_hold was already long from bar 1 — structural, expected
   of any trend filter, not a signal of a problem.
4. **track4_meanrev has exactly one data point** (its inception mark).
   No interpretation is possible yet and none is offered — flagged
   honestly rather than padded.
5. **The order-book logger's zero rows is a setup-timing artifact**,
   fully explained by the scheduled-task metadata above, not a live
   incident.
6. **The Fisher fix deploy remains clean two days in** — no risk events,
   no halts, no crash-loop signs anywhere in the engine's logs or state.

## 5. Tweaks needed: **none required right now**

Every flat/zero reading above traces to expected cadence or just-registered
timing, not a defect — there is nothing in this data that calls for a code
change today. The levers already on record for when Zane wants to act
remain the same three, restated here (not re-argued) so this report stands
alone:

- **Trade frequency** — breadth/multi-asset sleeves is the recommended
  path (Grid E showed faster timeframes fail on both frequency and R;
  the bottleneck is the R:R gate, not the timeframe). A pre-registered
  R:R-gate sensitivity study is the second option. Both undecided,
  neither urgent.
- **Gold 2-Step reparameterization** — built and stress-tested on staging
  (6/6 scenarios passing, including the HWM-reset rehearsal), but Step-4
  deploy and the config flip remain explicitly HELD by Zane
  ([GOLD_2STEP_REPARAMETERIZATION.md](GOLD_2STEP_REPARAMETERIZATION.md)).
  Nothing time-sensitive forcing a decision.
- **0xArchive subscription** — gates both the order-book imbalance
  backtest (Part C) and OI Phase 2 cascade-fade research; also HELD, also
  not time-sensitive. The zero-cost hourly logger (§3) accrues evidence
  in the meantime regardless of this decision.

## Reproduce

```powershell
# Live engine + forward-test + order-book state (read-only)
railway run --service btc-signal-bot python forward_test.py --report
railway run --service btc-signal-bot python scripts/orderbook_logger.py --report
Get-ScheduledTask btc-trend-forward-tick, btc-orderbook-logger | Get-ScheduledTaskInfo
```
Live Supabase queries (engine_state, portfolio_telemetry, pending_signals,
trade_execution_ledger, risk_events, market_state, trend_forward_marks,
orderbook_snapshots) run directly against project `lnycymeylmhjqpwtdint`.
