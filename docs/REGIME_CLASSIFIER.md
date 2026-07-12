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

