# Study Batch 5 — Pre-Registered (synthesis of two adversarial reviews)

Registered 2026-07-12 (this doc committed BEFORE any result). Source: the
uploaded pre-registration (Claude + Grok adversarial reviews, 2026-07-12).
All grids FIXED here. All cells reported regardless of outcome. Zero new
data cost — reuses existing frozen snapshots throughout. **Source-quality
rule:** the external SSRN figures (70 tokens, ~39.6%/yr, Sharpe 0.96–1.69)
are UNVERIFIED single-paper claims — they motivate tests, they are not
evidence in our sample.

Run order (fixed): **S-F → S-A → S-D → S-B → S-C → S-E → S-G.**

## S-F — Methodology retrofit (runs FIRST; others report against its bars)

1. Replace shuffle/shift nulls with **stationary block bootstrap** (mean
   block ~20 days, 10,000 reps) across: trend tournament, Track 4 robust
   cell, live-engine backtest. Re-report every existing verdict old-vs-new
   (tournament may move either way).
2. Add **Deflated Sharpe Ratio** to the standard cell report (inputs:
   trials/study, skew, kurtosis, track length).
3. Publish the **effective-bets basis**: pairwise correlation matrices of
   the 7 assets AND the 7 trend-strategy return streams; N_eff for both.
4. **Hierarchical pooling** on the tournament: posterior on the common
   trend effect across assets/variants.

## S-A — Track 4 Round 5R: joint stop×target grid (highest priority)

Adjudicates the review disagreement on whether Track 4-Comp's NULL is final.
Base: robust cell (long-only, 4H Fisher ≤ −1.25, 12H SMA30 bias), frozen,
same window as Rounds 3–4. **Grid: exits {first_profit, +0.5R, +1.0R,
+1.5R target} × stops {none, 2.5×ATR, 3.5×ATR} = 12 cells.** R vs the stop
where one exists; no-stop cells report R-equiv vs 3.5×ATR for comparability.
Predictions: Claude — targets lift avg win enough that ≥1 stopped cell
turns positive (Comp NULL premature); Grok — no stopped cell survives (edge
= tail compensation). **Kill: a stopped cell must be positive net of 14 bps
RT AND clear the S-F block-boot bar; else Comp NULL CONFIRMED.**

## S-D — Reversion asymmetry diagnostic (not a strategy)

Conditional on 4H Fisher crossing ±{1.0, 1.25, 1.5}, distribution of forward
{6, 24, 72}-bar returns, long side vs short side separately. Report effect
sizes + block-boot CIs. No trading rule. Purpose: if asymmetry is real in
our sample, it justifies Track 4's long-only restriction structurally.

## S-B — Breakout wide-stop / time-invalidation re-test

The 0/24 null tested tight stops only. Base: original breakout (HTF-trend
direction, volume-confirmed), frozen. **Grid: stops {2.0×ATR, 3.0×ATR,
time-invalidation (exit if not +0.5R within 12 bars, no price stop)} ×
targets {2R, trail 2.5×ATR} × bias {Fib-S/R fixed} = 6 cells, 4H trigger
only.** Prediction: time-invalidation cells outperform price-stop cells.
Kill: family standard (positive net + block-boot bar).

## S-C — Medium-horizon reversal (8–10 week gap)

Single-asset (BTC 1D): if trailing {56, 70}-day return in its own bottom
{10th, 20th} percentile (rolling 2-year window) → long, hold {14, 21} days,
**no stop but sized so worst historical MAE × size ≤ 1% equity** (sizing-
bounded, the Track 4 lesson as design not patch). 2×2×2 = 8 cells. Breadth
(7-asset frozen): weekly, long bottom-2 by 8-week return, inverse-vol
weights, flat otherwise = 1 cell. Prediction: single-asset likely
underpowered; breadth is the real test. Kill: block-boot bar; breadth must
additionally beat equal-weight buy-and-hold on Sharpe AND maxDD.

## S-E — Funding gate on Track 4 dips

One cell: Track 4 robust config + veto entries when funding percentile ≥ 90
(crowded-long dip). Frozen/free. Prediction: small worst-MAE improvement,
negligible on return.

## S-G — High-vol conditioning (scope-limited)

Applied to the S-C breadth cell ONLY: same rule, active only when 30-day
realized vol > its rolling median. 1 cell.

## Explicitly NOT in this batch

- OBI alpha tests at any frequency — horizon mismatch (documented OBI power
  is seconds-to-minutes vs our hourly snapshots). The Propr HFT-rule
  concern is **resolved** (no min-hold/HFT restriction per Propr docs), but
  the data-resolution mismatch blocks OBI alpha-testing independently; the
  hourly logger stays fine for attribution only.
- 0xArchive / Phase 2 — held on cost.
- Any 1H/15m variant — the frequency ceiling is a well-established internal
  result; respected.

## Verdicts index (filled as studies complete)

| Study | Verdict | Doc |
|---|---|---|
| S-F | PENDING | docs/STUDY_BATCH5_SF.md |
| S-A | PENDING | this doc / SF |
| S-D | PENDING | |
| S-B | PENDING | |
| S-C | PENDING | |
| S-E | PENDING | |
| S-G | PENDING | |
