# OI × Liquidation Confluence — Phase 0 (data reality) + Phase 1 (exhaustion stand-down gate)

> **SUPERSEDED 2026-07-10:** results below were computed under the Fisher gain bug (fixed in 9da31ee - the recursion applied Ehlers' x2 twice, saturating the indicator). Corrected re-run results and the full blast-radius report: docs/FISHER_FIX_REVERIFICATION.md.

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

## Phase 1 results (single run, 2026-07-10, sweep_id 01KX3RAJ1ADP07AQHGB8608BT5)

Funding series: 27,142 hourly rows, 2023-05-12 → 2026-07-09, frozen to
`research/data/BTC_funding_history.json` before the run (84 sub-gaps >1.5h
across 3.2 years — exchange maintenance windows; the trailing-window
percentile is computed over whatever prints exist, unaffected).

**Regression check PASSED:** the 4h/1h gate-off baseline reproduces the
stored V2.3 Grid C cell exactly (9 trades, 4-5, +1.28R, PF 1.15, maxDD
6.77R, supp_rr 87).

| Pair | Gate | Trades | W-L | Net R | PF | maxDD | supp_std |
|---|---|---|---|---|---|---|---|
| 4h/1h | off | 9 | 4-5 | **+1.28** | 1.15 | 6.77 | 0 |
| 4h/1h | F≥85 | 8 | 3-5 | −0.69 | 0.92 | 6.77 | 1 |
| 4h/1h | F≥90 | 8 | 3-5 | −0.69 | 0.92 | 6.77 | 1 |
| 1d/4h | off | 4 | 0-4 | −5.38 | 0.00 | 5.38 | 0 |
| 1d/4h | F≥85 | 3 | 0-3 | **−3.91** | 0.00 | 3.91 | 1 |
| 1d/4h | F≥90 | 3 | 0-3 | −3.91 | 0.00 | 3.91 | 1 |

**Suppressed-entry attribution (the pre-registered deliverable):**

| Pair | Suppressed entry | Direction | Funding state | Baseline outcome | Gate delta |
|---|---|---|---|---|---|
| 4h/1h | 2026-03-19 11:59 UTC | SHORT | ≤10th pctile (shorts crowded) | **+1.96R winner** (target) | **−1.96R** |
| 1d/4h | 2024-09-22 23:59 UTC | LONG | ≥90th pctile (longs crowded) | **−1.47R loser** (stop) | **+1.47R** |

Both thresholds (85/90) bind on the same two entries — both moments were
beyond the 90th/10th extremes, so the threshold axis is inert on these
windows.

### Honest read

1. **The funding-only condition barely binds at this system's entry
   moments:** 2 of 13 baseline entries across ~208 days (4h/1h) + ~2.3
   years (1d/4h). Fresh confluence entries mostly occur mid-range funding
   — the crowding extreme arrives after the trend is established, which is
   consistent with the mechanism but leaves the gate with almost nothing
   to act on in a vectorized entry-gate role.
2. **Split verdict at n=2 — strictly uninformative.** One suppression was
   the window's second-best winner (a crowded-short continuation that
   worked), one was exactly the crowded-long failure the hypothesis
   predicts. Combined delta −0.50R. No evidence of value, no evidence of
   harm, and **no case whatsoever for gating the live config.**
3. **This tested the weaker half of the pre-registered condition.** The
   source research frames OI as the effect modifier — funding alone was
   the Phase 0 fallback, not the hypothesis. The 4 funding∧OI conjunction
   cells are coded and dormant; unlocking any OI history source (AWS
   requester-pays creds ≈ cents, free Coinalyze key, or Pinax key) makes
   them a one-command re-run. **However:** the conjunction binds strictly
   less often than funding alone, so on these same windows it can only
   act on ≤2 entries — a conjunction re-run cannot produce a meaningful
   entry-gate verdict here either. Its real home is Phase 2.
4. **Where the value in this research actually sits (per its own logic):**
   the fuel-check stack (OI z + funding skew + OI contraction on flush)
   is designed for EVENT selection — deciding which liquidation cascades
   are fadeable — not for suppressing a handful of trend entries. That is
   Phase 2's H1 on 0xArchive event data (Dec 2025+, ~7 months, small-n
   caveat pre-stated), which needs a 0xArchive account and separate
   approval. The Phase 1 infrastructure built here (funding-history
   plumbing, causal trailing-percentile machinery, gate wiring) carries
   over directly.
5. **Recommendation:** do not adopt the stand-down gate; park the
   funding∧OI conjunction until OI data exists AND a higher-frequency
   consumer (Phase 2) justifies it; treat Phase 2 H1 as the decision
   point for whether this research program gets its expensive
   infrastructure.

## Commits

1. `research: OI/funding + liquidation data availability check (Phase 0)` (this commit)
2. `feat: trend-exhaustion funding/OI stand-down gate (Phase 1 wiring)`
3. `docs: phase 0+1 results, real numbers only`
