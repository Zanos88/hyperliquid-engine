# OI × Liquidation Confluence — Phase 0 (data reality) + Phase 1 (exhaustion stand-down gate)

Date: 2026-07-09. Status: Phase 0 **COMPLETE** (real numbers below); Phase 1
protocol **pre-registered** in this doc + implemented; results appended after
the single sweep run. Source: `oi-liquidation-confluence-validated.pdf`
(Zane's cross-checked research) + `OI_LIQUIDATION_PHASED_BUILD.md` (the
phased build spec — its corrections are binding). Phase 2 (event-driven tick
replay, cascade-fade H1, pullback H2, accumulation-block H3) is **not
started** — separate approval required.

> **RESEARCH ONLY.** No trades; live trend engine and tsmom30 forward test
> untouched; zero Bullphoric reuse (the PDF's "cluster evaporation /
> sweep-and-reclaim / burn-in ledger" references are the OTHER bot — nothing
> here ports that code). Compliance flag carried verbatim: sub-second
> liquidation-slice tactics are HFT-adjacent and prohibited on the Propr
> challenge; nothing HFT-adjacent is built in this repo, full stop.

## Phase 0 — data availability (verified 2026-07-09, real numbers)

### 0.1 Funding history — CONFIRMED, official, free, backtestable

`POST https://api.hyperliquid.xyz/info {"type":"fundingHistory","coin":"BTC",
"startTime":...}` — verified empirically:
- Earliest BTC record: **2023-05-12 00:00:00 UTC** (rate −0.00061).
- Cadence: **hourly**; pagination 500 rows/page (~56 pages ≈ 27.7k rows to
  present); current through fetch time (latest row ~1h old).
- Coverage vs existing backtests: the full 4h/1h window (2025-12→2026-07)
  AND the full 1d/4h window (2024-03→2026-07) are covered with >1 year of
  history to spare for the 30-day trailing normalization warm-up.

### 0.2 OI history — EXISTS officially, but requester-pays (not free-anonymous)

- `metaAndAssetCtxs` returns **current-snapshot** OI only (verified: BTC
  `openInterest` 37,929.3 at check time; no history parameter) — the build
  doc's suspicion was correct: "polled" = live monitoring, not history.
- Hyperliquid's official S3 archive `s3://hyperliquid-archive/asset_ctxs/
  [date].csv.lz4` DOES contain historical asset contexts (OI + funding +
  mark px), uploaded ~monthly with no timeliness guarantee — but the bucket
  is **requester-pays**: anonymous HTTPS GET returns 403 (verified);
  access needs AWS credentials (`aws s3 cp … --request-payer requester`,
  transfer cost ~cents/GB).
- Third-party historical OI (all signup-gated): Coinalyze (free API key),
  Pinax/The Graph token API (key), Amberdata (paid), Tardis (paid).

**Pre-registered decision rule applied:** an hourly-or-better OI series is
NOT obtainable without account credentials this session → **Phase 1 runs the
funding-only gate variant**, stated plainly. The OI plumbing is built and
dormant; supplying any one of {AWS creds, Coinalyze key, Pinax key} unlocks
the full funding∧OI conjunction as a pre-registered re-run (one command).

### 0.3 Liquidation-event history (Phase 2 input) — depth corrected

Per the validated PDF (§1) + 0xArchive's own material: **liquidation events
from Dec 2025 (~7 months, 150+ symbols)** — the build doc's estimate was
right; the "history starts April 2023" figure on 0xArchive's site refers to
**order-book snapshots (24.6B) and fills (2.3B), not liquidation events**.
Native HL API has no liquidation-history query (the PDF flags that claim as
third-party conflation). Access: account + API key; pricing page is
account-gated — **terms/cost reported as unverifiable without signup; any
spend is Zane's call.** Phase 2's H1 sample-size caveat stands: ~7 months of
event data is much less history than anything tested in this program.

## Phase 1 — trend-exhaustion stand-down gate (pre-registered protocol)

**Hypothesis (PDF §2.3, mechanism (c) only — (a)/(b) deferred to Phase 2):**
a trend running on funding-extreme, OI-maxed leverage is crowded, not
conviction; fresh trend entries in the crowded direction should be
suppressed. Cheapest test: an additive entry gate on the existing 4h/1h
trend backtest, wired exactly like V2.2's Fisher-4H entry filter.

- **Gate (directional):** suppress a LONG entry when the trailing-30-day
  funding percentile ≥ P; suppress a SHORT entry when percentile ≤ 100−P.
  (Full spec is `AND OI z-score ≥ Z` vs its trailing 30-day distribution —
  dormant this run per §0.2; the code takes the OI series as an optional
  input and the sweep records `oi_used: false`.)
- **Causality:** funding percentile computed per trigger bar from the
  trailing 30-day (720-row) hourly window ending at the last funding
  timestamp ≤ the trigger bar's close (bisect join, same idiom as the
  Fisher-4H `_fisher4h_at`). Never full-series normalization.
- **Placement:** after the R:R gate (same as Fisher-4H), so suppression
  counts isolate trades that would otherwise have been taken;
  `SuppressedSignal(kind="exhaustion_standdown")`.
- **Sweep (Grid D, 10 runs, no full cross):** {4h/1h, 1d/4h} × default
  indicators × structural stop × fib_extension_preferred target × {gate off,
  P ∈ {85, 90} × (OI dormant)} — off-baselines must reproduce the stored
  V2.3 cells (regression check). With OI dormant the on-variants are 2 per
  TF pair → **6 runs total this pass** (off + P85 + P90 per pair); the
  remaining 4 (Z ∈ {1.5, 2.0} conjunctions) run when OI data is unlocked.
- **Read (pre-registered):** ~6–9 trades per baseline cell → this is
  ATTRIBUTION evidence, not statistics. Deliverable: per-cell net R, trade
  count, `suppressed_standdown` count, and a per-suppressed-entry table
  (was the suppressed trade a winner or loser in the baseline?). All cells
  reported. No significance claims at this n.
- **Frozen inputs:** the full funding history is snapshotted to
  `research/data/BTC_funding_history.json` before the sweep.

## Phase 1 results

*(appended after the single sweep run)*

## Commits

1. `research: OI/funding + liquidation data availability check (Phase 0)` (this commit)
2. `feat: trend-exhaustion funding/OI stand-down gate (Phase 1 wiring)`
3. `docs: phase 0+1 results, real numbers only`
