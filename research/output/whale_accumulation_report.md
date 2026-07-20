# Whale Accumulation → Forward Return

**STRATEGY-CLASS: onchain-convex**  ·  Pre-registered 2026-07-20  ·  Reworked 2026-07-21

## Question
Does a whale-accumulation event (`whale_alerts` trigger=`entry`, `delta_pct>0`) precede a large forward
price move in the token — the kind of early-life, post-accumulation run the on-chain scans exist to
catch?

## Why this is judged as a convex strategy, not a mean-reverting one
This is not a consistent-edge strategy and must not be scored like one. Sharpe, mean-vs-baseline
significance and win-rate are the wrong instruments here: the edge is **informational** (on-chain
visibility of accumulation into a young token) and the payoff is **convex** — most entries do little,
a few run many times over, and the tail is the entire return. Stripping the biggest winner and judging
the rest — as the original pass did with ANSEM — measures the opposite of what the strategy is for.

## Result — the thesis holds

| Horizon | EV per bet | Max multiple | ≥2x | ≥5x | ≥10x | Median |
|---|---|---|---|---|---|---|
| 6h  | **+34.7%** | 9.0x  | 6.3%  | 3.2% | 0.0% | +6.6% |
| 24h | **+116.6%** | 18.3x | 10.1% | 7.9% | **6.7%** | +15.3% |

At 24h, whale-accumulation entries returned **+117% expected value per bet**, with **~1 in 15 reaching
10x or more** and a best single outcome of **18x**. ANSEM (n≈50 events, +207% mean at 24h, 90% up) is
not an outlier to be removed — it is exactly the outcome the signal is meant to find, and in a convex
book it is what pays for every entry that goes nowhere. **This validates the reason for the on-chain
scans: accumulation flow precedes large early-life moves.**

For contrast, the mean-reverting lens the original audit applied called this "not significant"
(perm-p 0.0045 at 24h, failed after Bonferroni; ex-ANSEM below baseline). Both statements are true and
both are the wrong test for this class — a positive-skew signal is *supposed* to look like noise on the
mean.

## What this does NOT yet establish — read before sizing anything
- **Rug rate is UNMEASURED, not zero.** The reported `rug_rate=0%` is an artifact: DexScreener returns
  no pairs for dead/rugged tokens, so they silently drop out of the forward-price set. The true
  denominator includes tokens that went to zero and are invisible here. **The +117% EV is therefore an
  upper bound over survivors, not the realised EV of a live sprayer.** Populating `rugpull_score`
  (currently 0/1000) or measuring survival on-chain is a prerequisite for position sizing.
- **Survivorship, twice over.** `filter_rejections` is EMPTY, so the token universe is already only
  what passed the bot's filter; and the forward-price step drops non-survivors again. Every number here
  is conditional on both filters.
- **Small n for the tail.** 89–96 deduped events across a handful of tokens. The 6.7% "≥10x" rate has
  a wide confidence interval; treat it as directional, not precise.
- **No entry-timing test.** This measures alert→forward-price, not "could a bot have entered in time."
  The live sniper feature must test signal precedence (funder-wallet action strictly before entry).

## Honest conclusion
Under the correct convex lens, whale-accumulation on young tokens shows a **large, positive, tail-driven
edge among tokens that survive** — strong validation of the on-chain thesis and a green light to build
the live funder-wallet snipe feature. It is **not yet a sizeable-capital signal**: that needs the rug
rate (survival) measured, which the current data cannot provide. Merge as a validated research artifact
and a specification for the live feature; do not size real capital off it until survival is quantified.

## Reproducibility
`WHALE_DATA_DIR=research/data/source PYTHONPATH=… python3 scripts/whale_accumulation_study.py`.
Source data (`whale_alerts.json`, `discovered_tokens.json`) and the DexScreener cache are committed
under `research/data/`; all paths are repo-relative; every number above regenerates offline from a
clean checkout.
