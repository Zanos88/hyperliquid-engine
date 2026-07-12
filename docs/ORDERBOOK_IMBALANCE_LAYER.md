# Order-Book Imbalance Entry-Timing Layer — Part A findings + locked definition

Date: 2026-07-11. Executes the ORDERBOOK_IMBALANCE_LAYER.md brief through its
own decision gate. **Part C (the two tests) has NOT run** — it is gated on the
historical-data decision below, per the brief.

## Part A — data availability (verified, real numbers)

1. **Live L2 snapshot: available, free, precise.** Public info endpoint
   `POST /info {"type":"l2Book","coin":"BTC"}` → **20 levels per side**, per-level
   `{px, sz, n}`, **millisecond timestamp** in the response (verified 2026-07-11
   15:53:20 UTC: top-10 bidVol 36.91 BTC vs askVol 46.22 → imbalance −0.112).
   N=10 is fully supported; the brief's contemporaneity requirement is satisfiable
   live (snapshot at bar close, ms-stamped).
2. **Historical depth: NOT freely available.** The official S3 archive has
   `market_data/[date]/[hour]/l2Book/BTC.lz4` but anonymous access returns **403**
   (verified) — same requester-pays wall as `asset_ctxs`. Requester-pays via AWS
   creds is possible but book files are orders of magnitude larger than candles
   (raw L2 feeds; months of history = real transfer cost, not cents).
3. **Shared cost decision (the brief's own instruction):** the practical historical
   source is **0xArchive — the SAME subscription Phase 2's cascade-fade needs**
   (books/fills to Apr 2023, liquidation events Dec 2025+). This is ONE cost
   decision covering both research lines, not two separate asks. Terms are
   account-gated (pricing page requires signup); any spend is Zane's call.

**Decision gate outcome:** no usable free historical depth → Part C backtests are
**pending the 0xArchive decision** (explicitly HELD by Zane 2026-07-12 — not
time-sensitive).

## Interim forward logging — RUNNING since 2026-07-12 (zero cost)

Per Zane's go-ahead: `scripts/orderbook_logger.py` captures one LIVE l2Book
snapshot per **1H bar close** into the additive `orderbook_snapshots` table
(top-10 imbalance + raw 20×2 levels as provenance; the ±0.15 threshold stays
locked — raw levels are not a re-tuning surface). Hourly boundaries cover
every track's 4H/12H/1D closes.

- **Contemporaneity guard (hard):** a snapshot is written only when captured
  ≤120s after the boundary it is stamped with; later runs skip loudly. This
  is the brief's own requirement — verified live: a run 15 min past the
  boundary refused to write.
- **Scheduling:** task `btc-orderbook-logger`, hourly at hh:00:45
  (`scripts/orderbook_tick.cmd`, log `%LOCALAPPDATA%\btc-orderbook\tick.log`).
  **Laptop-off hours are permanent gaps** — the book is live-only, no
  self-healing exists; the eventual Part C attribution claims only covered
  entries (`--report` prints coverage).
- **Consumption plan:** future entries are attributable by joining
  `pending_signals.created_at` (the engine timestamps every Frame-A signal)
  and the forward tracks' flip marks against snapshot boundaries; the locked
  gate (±0.15) is then evaluated per entry with zero look-back bias, because
  every snapshot predates the analysis by construction.

## Part B — the ONE pre-registered definition (locked now, before any data)

- `imbalance = (bidVol_top10 − askVol_top10) / (bidVol_top10 + askVol_top10)`,
  range −1..+1, **N = 10 levels** (default stated by the brief; verified available).
- **Gate rule, identical for both tests:** at the moment an existing system fires
  an entry, require `imbalance ≥ +0.15` for a long; `≤ −0.15` for a short.
  Threshold **+0.15** is locked from the brief's stated 0.15–0.20 range at the
  LEAST restrictive bound — both base systems are tiny samples (8 and ~17 trades);
  a tighter gate risks filtering everything and learning nothing. Untuned default,
  stated plainly.
- **No threshold sweep, no window sweep, no per-system tuning.** A null with this
  definition ends this round; any different definition is a new, separately-scoped
  hypothesis.
- Time alignment: the book snapshot must carry a timestamp within the entry bar's
  close ±1 minute (ms stamps make this checkable); looser matches invalidate the
  test.

## Part C — test designs (recorded now; status: PENDING DATA DECISION)

- **Test 1 — live trend system (4h/1h corrected baseline, 8 entries):** apply the
  locked gate at each stored entry_ts; report kept vs filtered entries and the
  resulting net R / PF delta with per-trade attribution (same shape as the OI
  stand-down table in docs/OI_LIQUIDATION_PHASE0_PHASE1.md).
- **Test 2 — Track 4 −1.25 cell (~17 entries,
  `research/output/track4_results_r4_sweep.json`):** same definition, same
  threshold, same reporting shape. (Coordination note: the Track 4-Comp stop
  rebuild in flight does not change this test's target — the r4_sweep trade list
  is frozen.)
- Results reported **side by side, never blended** — a gate that helps one system
  and hurts the other is information, not a wash.
- Expectation-setting (brief's own standard): n=8 and n≈17 ⇒ attribution-grade
  evidence at best. SIMULATED caveats apply.
