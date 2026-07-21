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

## Result — convex UPSIDE is real among survivors; the thesis is NOT yet validated

| Horizon | EV per bet | Max multiple | ≥2x | ≥5x | ≥10x | Median |
|---|---|---|---|---|---|---|
| 6h  | **+34.7%** | 9.0x  | 6.3%  | 3.2% | 0.0% | +6.6% |
| 24h | **+116.6%** | 18.3x | 10.1% | 7.9% | **6.7%** | +15.3% |

At 24h, **among tokens that survived to trade**, whale-accumulation entries showed **+117% EV | survived**,
~1 in 15 reaching ≥10x, best single outcome 18x. The ANSEM-shaped tail is the right thing to be
looking for in a convex book. **But this is an upper bound over survivors, not a validated edge — two
required class-C checks are unmeasured, and both are load-bearing:**
- **Rug rate is unmeasured (survivorship).** `rug_rate=0%` only because DexScreener has no dead tokens.
  Realised EV = `P(survive)·E[ret|survive] − P(rug)`; with `P(rug)` unknown (and plausibly dominant for
  young pump.fun pairs) the SIGN of realised EV is unknown. `+117%` is `EV|survived`, not EV.
- **Precedence is untested.** The thesis is that accumulation *precedes* the move. The study measures
  alert→forward-price but never verifies the tracked-wallet action came strictly BEFORE entry and entry
  before the pump. The alert could be concurrent or lagging. Untested = no demonstrated informational edge.
- The "6.7% reach ≥10x" at 24h is **6 events, all ANSEM** — one pump episode, effective n≈1. Directional,
  not a rate with a usable CI.

So: the on-chain thesis is **plausible and worth building for**, not proven. What IS established — the
data reproduces, the tail is large and real among survivors, and the convex lens is the correct frame —
makes this a solid **spec for the live funder-wallet snipe feature**, whose whole job is to measure the
two things this study could not: precedence and survival.

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

## Conclusion
Merge as a **reproducible research artifact and the specification for the live funder-wallet snipe
feature** — NOT as a validated signal. The convex upside among survivors is real and the frame is
correct, but the thesis stays UNTESTED until precedence and rug/survival are measured. Do not size any
capital off it. The next deliverable is the live feature that measures precedence and survival on new
pairs as they launch — that is where the edge is actually proven or refuted.

## Reproducibility
`WHALE_DATA_DIR=research/data/source PYTHONPATH=… python3 scripts/whale_accumulation_study.py`.
Source data (`whale_alerts.json`, `discovered_tokens.json`) and the DexScreener cache are committed
under `research/data/`; all paths are repo-relative; every number above regenerates offline from a
clean checkout.
