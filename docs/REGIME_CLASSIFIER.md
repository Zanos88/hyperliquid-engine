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

<!-- Part B (locked definition), Part C (instance count / gate), and Part D
     (retroactive split + per-strategy verdicts) are appended by their own
     commits, in order, after this Part A section is committed. -->
