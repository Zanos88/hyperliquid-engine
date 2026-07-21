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

| Horizon | EV \| survived | Max multiple | ≥2x | ≥5x | ≥10x | Median |
|---|---|---|---|---|---|---|
| 6h  | **+34.7%** | 9.0x  | 6.3%  | 3.2% | 0.0% | +6.6% |
| 24h | **+116.6%** | 18.3x | 10.1% | 7.9% | **6.7%** | +15.3% |

At 24h, **among tokens that survived to trade**, whale-accumulation entries showed **+117% EV | survived**,
~1 in 15 reaching ≥10x, best single outcome 18x. The ANSEM-shaped tail is the right thing to be
looking for in a convex book. But this is an **upper bound over survivors, not a validated edge**, and
the class-C checks below decide whether it is real.

For contrast, the mean-reverting lens the original audit applied called this "not significant"
(perm-p 0.0045 at 24h, failed after Bonferroni; ex-ANSEM below baseline). Both statements are true and
both are the wrong test for this class — a positive-skew signal is *supposed* to look like noise on the
mean.

## Class-C checks — the ones the thesis actually rests on
These are now **measured** from the committed data (`convex_risk` in the results JSON), not asserted.
Three of the four temper the thesis; the fourth is unmeasurable and stays disclosed.

**1. Hit-rate confidence — the tail rate is one token, not a rate.**
The ≥10x "6.7%" at 24h is 6 events but from **1 distinct token** (all ANSEM). Reported at the honest
unit — the token/episode — the interval is enormous:

| Horizon | ≥10x events | Event-level 95% CI | Distinct tokens hit | Episode-level 95% CI |
|---|---|---|---|---|
| 6h  | 0 / 95 (0.0%) | [0.0%, 3.9%] | 0 / 4 | [0.0%, 49.0%] |
| 24h | 6 / 89 (6.7%) | [3.1%, 13.9%] | 1 / 4 | [4.6%, 69.9%] |

The event-level CI is over-precise (overlapping windows on one pump are not independent). The
episode-level [4.6%, 69.9%] is the honest statement: **effective n ≈ 1** for the tail.

**2. Adverse selection — MEASURED, and it is high.** Tracked wallets post `exit` alerts *inside* the
window we hold, frequently, and sometimes it is the very wallet whose accumulation we followed:

| Horizon | Any tracked wallet exits in-window | The same wallet we followed exits in-window |
|---|---|---|
| 6h  | 62.1% | 10.5% |
| 24h | **86.5%** | **12.4%** |

At 24h, in **86.5%** of held windows a tracked wallet is selling while we hold, and in **12.4%** it is
the exact wallet we followed — i.e. we are frequently its exit liquidity. The accumulation signal and
distribution overlap heavily in time. This is a real, adverse finding, not a hypothetical.

**3. Precedence — in-sample proxy only, and weak at short horizons.** Share of events where a higher
price appears *after* entry within the window (the move develops post-signal): **1h 10.4% · 6h 58.9% ·
24h 76.4%**. So the move, where it exists, mostly develops on the 6–24h scale. But this is a price
proxy — the source has **no on-chain tx timestamps**, so true "wallet action strictly before entry"
precedence is still untested and remains the job of the live funder-wallet feature.

**4. Rug rate — UNMEASURABLE from this dataset (survivorship).** `rug_rate=0%` only because dead/rugged
tokens carry no price series in the source; all 4 tokens here survived. Realised EV =
`P(survive)·E[ret|survive] − P(rug)`, and with `P(rug)` unmeasurable the **sign of realised EV is
unknown**. `+117%` is `EV | survived`. Ruin at equal-weight spray (survivor-only): loss rate 28–40%,
worst losing streak up to 8, book multiple 1.35x (6h) / 2.17x (24h) — an upper bound that ignores the
rugged tail.

## What this does NOT yet establish — read before sizing anything
- **Rug rate is UNMEASURED, not zero** (check #4). Populating `rugpull_score` (currently 0/1000) or
  measuring survival on-chain is a prerequisite for position sizing.
- **Adverse selection is high** (check #2): being tracked-wallet exit liquidity is the norm at 24h, not
  the exception — sizing/exit rules must front-run it, not ignore it.
- **Survivorship, twice over.** `filter_rejections` is EMPTY, so the universe is already filter-passed;
  the forward-price step drops non-survivors again. Every number is conditional on both filters.
- **The tail is effectively one token** (check #1): the ≥10x episode CI is [4.6%, 69.9%].
- **Precedence is a price proxy, not tx-level** (check #3): no on-chain timestamps in this dataset.

## Conclusion
Merge as a **reproducible research artifact and the specification for the live funder-wallet snipe
feature** — NOT as a validated signal. The convex upside among survivors is real and the frame is
correct, but the thesis stays UNTESTED: rug rate is unmeasurable here, precedence is only a price proxy,
the tail is one token, and **adverse selection is measured and high (86.5% at 24h)**. Do not size any
capital off it. The next deliverable is the live feature that measures rug/survival and tx-level
precedence on new pairs as they launch — that is where the edge is actually proven or refuted.

## Reproducibility
`WHALE_DATA_DIR=research/data/source PYTHONPATH=… python3 scripts/whale_accumulation_study.py`.
Source data (`whale_alerts.json`, `discovered_tokens.json`) and the DexScreener cache are committed
under `research/data/`; all paths are repo-relative; every number above regenerates offline from a
clean checkout.
