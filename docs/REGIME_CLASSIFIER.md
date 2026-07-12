# Regime Classifier — Bull/Bear Definition (pre-registered, blind, retroactive)

Started 2026-07-12. Brief: `REGIME_CLASSIFIER.md`. Motivated by S-B (a
time-invalidation breakout cleared the block-bootstrap bar but DSR rejected it
as bull-market beta from a 162-day hold). Real question: **does trend/breakout
work conditional on a properly-defined bull regime?** The trap: defining the
regime after seeing which window won just relabels the lucky stretch in a new
shape.

> **Locked design principle.** The classifier is defined once (Part B),
> committed, and **never adjusted after seeing how any strategy performs under
> it** (Part D). If the first version doesn't "work," that is a real result, not
> a reason to iterate the definition. Pre-registration is enforced by the commit
> order: Part B lands *before* Parts C/D are ever computed.

> **SIMULATED / backtest only.** Same block-bootstrap + Deflated-Sharpe standard
> as Study Batch 5 — the classifier does not get a lighter bar for being new.

## Part A — data availability (what is genuinely free vs a spend decision)

Confirmed against the repo and the known data-vendor landscape:

| Source | Status | Coverage | Use |
|---|---|---|---|
| **Price structure** (`strategy.bias_4h.detect_swings`) | **Free, in hand** | full 1d history (BTC 2020-08 → 2026-07; 7-asset panel same span) | structure component |
| **Halving dates** | **Free** (calendar fact) | 2020-05-11, 2024-04-19 (2028 est. out of window) | halving-phase component |
| **Funding rate** (`research/data/BTC_funding_history.json`) | **Free, frozen** | **2023-05-12 → 2026-07-09 only** | funding component (abstains before it) |
| On-chain: MVRV, exchange netflows, active addresses | **Paid / gated** | — | **EXCLUDED** (held, see below) |

**On-chain finding (checked, not assumed):** the metrics named in the brief
(MVRV, exchange netflows, active addresses) are served by Glassnode / CryptoQuant
/ Coin Metrics-class providers. Their **API access to full historical series is
paid** (subscription tiers); free tiers are UI-only or throttled to recent/
sampled data with no reliable bulk-historical API. A few narrow free proxies
exist (e.g. raw active-address counts via blockchain.com charts, some Coin
Metrics *community* series), but they are partial, inconsistently defined versus
the paid metrics, and not a clean substitute for MVRV or exchange netflows.

**Decision: on-chain is EXCLUDED from the classifier**, held exactly the way
0xArchive and Coinalyze were — a separate spend decision for Zane, **not built
into this study by default**. The Part B classifier therefore uses only the three
confirmed-free components (structure + halving + funding). If Zane later approves
an on-chain spend, a v2 classifier can add it — as a *new*, separately
pre-registered definition, never a retro-tune of this one.

## Part B — the classifier, LOCKED (committed before any Part C/D result)

Composite daily label, causal (no lookahead), from the three free components.
**Every constant below is the registered rule** (`scripts/regime_classifier.py`),
fixed now and never tuned after seeing Part C/D. Per-bar labels + component votes
are emitted to `research/output/regime_labels_btc.json` so the definition is
fully inspectable.

- **Structure** (`detect_swings`, fractal_width 2, trailing **120** daily bars):
  last two swing highs and lows → **higher-high AND higher-low = BULL;
  lower-high AND lower-low = BEAR; else NEUTRAL.**
- **Halving phase** (days since most-recent halving; halvings 2020-05-11,
  2024-04-19; cycle ≈ 1400d) — *stated as a heuristic under test, not assumed
  true*: **0–400 expansion = BULL; 400–550 peak-and-decline = BEAR; 550–1100
  accumulation = NEUTRAL; 1100+ pre-halving run-up = BULL.**
- **Funding** (30-day avg funding, percentile within its trailing **365-day**
  distribution): **≥70 = BULL; ≤30 = BEAR; else NEUTRAL. ABSTAINS** until 365d of
  funding history exists (funding starts 2023-05-12 → abstains before ~2024-05).
- **Combination:** among non-abstaining components, **BULL if ≥2 vote BULL, BEAR
  if ≥2 vote BEAR, else NEUTRAL.** When funding abstains, the two remaining
  components must **both** agree for a directional label.

**Label distribution on BTC 1d (2020-08-19 → 2026-07-08, 2150 bars):**
**BULL 405 · BEAR 210 · NEUTRAL 1535 (71%).** This is a *property of the locked
rule, reported not tuned.* The pre-2024 era is almost entirely NEUTRAL because
funding abstains and structure vs halving-phase routinely disagree — e.g. the
Nov-2021 bull top scores structure=BULL but halving=BEAR (peak-and-decline) →
NEUTRAL; the entire 2021 bull is **not** captured. The single decisive BULL
stretch is **2024–2025**, where all three components align in post-halving
expansion. **The 2021 bull being uncaptured is deliberately left as-is** —
adjusting the definition to capture it after the fact is exactly the circularity
this study exists to avoid. It directly foreshadows the Part C gate.

## Part C — regime-instance count (the GATE before Part D)

Maximal contiguous runs ≥ **21 days**, then runs of the same label separated by
≤ **90 days** merged into distinct episodes (`research/output/regime_instances.json`).
Panel assets have **no per-asset funding frozen**, so their funding component
abstains → they are classified from structure + halving only (2-of-2).

**BTC 1d — 4 bull episodes, 1 bear episode:**

| | dates | days |
|---|---|---|
| bull | 2020-10-14 → 2021-02-24 | 134 |
| bull | 2023-10-08 → 2024-02-24 | 140 |
| bull | 2024-11-15 → 2024-12-27 | 43 |
| bull | 2025-04-27 → 2025-05-23 | 27 |
| bear | 2025-06 | 23 |

**Panel (6 alts):** 24 bull episodes total, **near-zero bear** (XRP 1, the other
five **zero**). They co-move (N_eff ≈ 2, factor study) and share BTC's halving
calendar and the same macro cycles — **not 6 independent instances.**

### Gate verdict — split by direction, unhedged

- **BULL: marginally testable, low power.** BTC's 4 bull episodes cluster into
  **~2 independent macro cycles** (2020–21 and 2023–25; the latter split into 3
  short episodes by the 90-day rule). Two independent cycles of short (27–140d)
  episodes is better than "one lucky stretch," but it is still very low power —
  a bull-regime edge resting on essentially two cycles cannot be strongly
  distinguished from cycle-specific luck. **Part D bull verdicts are capped at
  *suggestive*, never *proven*.**
- **BEAR: not testable.** BTC has a single 23-day bear episode (2025-06 — not
  even the 2022 bear, which the locked rule scores NEUTRAL: structure BEAR but
  halving in "accumulation" and funding abstaining). Five of seven assets have
  zero bear episodes. **The classifier does not identify bear regimes in this
  record**, so **every Part D bear-regime verdict is *insufficient-data* by
  construction** — a property of the locked definition, reported not patched.

## Part D — retroactive regime split (blind, block-boot + DSR)

Locked labels applied to strategies already tested. The **regime filter is an
added degree of freedom, counted in the DSR trials** (tournament: 7 variants × 3
regimes = 21). Block-boot 3000 reps, ppy 365. `research/output/regime_split.json`.

### Trend tournament (BTC 1d, per-bar block-boot + DSR) — the primary test

| Regime | n bars | family luck bar | best variant Sharpe | DSR | clears bar? |
|---|---|---|---|---|---|
| BULL | 405 | **+4.16** | sma50 **+3.00** | 0.90 | **no** |
| BEAR | 210 | +4.23 | sma50 +1.97 | 0.34 | no |
| NEUTRAL | 1534 | +0.95 | sma100 +0.37 | 0.12 | no |

**Verdict: regime-dependent in raw Sharpe, but the dependence does NOT cross into
significance.** Trend genuinely does better in the bull regime (best Sharpe 3.00
vs 0.37 in neutral) — but **no variant clears its within-regime luck bar in any
regime, bull included.** The reason is the honest one: conditioning on bull
raises the observed Sharpe *and* the family-max luck bar together (bull returns
are trendier, so the null family-max is higher too, 4.16), and the observed still
falls short; DSR < 0.95 everywhere. **Conditioning on a properly-defined bull
regime does not manufacture a provable trend edge** — the direct answer to the
S-B-motivated question. Capped at **SUGGESTIVE** by the Part C gate (only ~2
independent bull cycles); not proven.

### S-B breakout (4h, no-stop hold-to-profit) — 75 trades

| Regime | n | wins | net %notional | worst MAE |
|---|---|---|---|---|
| BULL | 14 | 14 | +13.19% | −4.15% |
| BEAR | 13 | 13 | +9.60% | **−27.74%** |
| NEUTRAL | 48 | 47 | +29.92% | −11.60% |

Net-positive in every regime — but that is the **~100% win-rate artifact** of the
no-stop hold-to-profit exit (the Track-4 family property), not an edge. The
honest regime signal is in the **tail: worst MAE −27.74% in BEAR** vs −4.15% in
BULL. The breakout's *danger* is regime-dependent (failed breakouts revert
hardest in bear) — consistent with S-B's original bull-beta finding, now with the
bear tail exposed. **Descriptive** (per-regime n=13–48); no luck bar cleared.

### Track 4 −1.25 (4h mean-reversion) — 17 trades

| Regime | n | net %notional | worst MAE | verdict |
|---|---|---|---|---|
| BULL | 2 | +1.22% | −2.65% | insufficient-data |
| BEAR | 2 | +0.54% | −0.58% | insufficient-data |
| NEUTRAL | 13 | +4.89% | **−16.53%** | descriptive |

**Overwhelmingly a NEUTRAL-regime phenomenon** (13 of 17 trades; its worst
hostage, −16.53%, is in neutral). Bull/bear n=2 each → insufficient-data.
Consistent with what Track 4 *is* — a chop/dip-buy mean-reversion trade, not a
trend strategy, so it fires in neutral markets, not directional regimes.

## Verdicts (per strategy, unhedged)

- **Trend tournament — regime-dependent but sub-significant.** Real bull
  out-performance (Sharpe 3.0 vs 0.37) that still fails the within-regime luck
  bar in every regime with DSR < 0.95 throughout. The bull-regime hypothesis is
  **SUGGESTIVE at best, not proven**, gated by only ~2 independent bull cycles.
  Bull-conditioning does not rescue trend into an edge.
- **S-B breakout — regime-dependent in tail risk, not in a provable edge.** Worst
  drawdown concentrated in bear (−27.7%); net is the no-stop win-rate artifact.
- **Track 4 −1.25 — insufficient-data for regime dependence; a neutral-regime
  strategy by nature** (bull/bear n=2).
- **Framework-level:** the classifier did *not* reveal a hidden regime-conditional
  edge. It worked as a discipline check — a locked definition that finds ~2 bull
  cycles and ~0 bear, and shows that even generous bull-conditioning leaves trend
  short of significance. The honest answer to "does trend/breakout work
  conditional on a bull regime?" is **not provably, on this data.**

