# Track 4 — Unconstrained Mean-Reversion (Fisher-4H exhaustion + SMA bias, no stop)

Run date: 2026-07-10, on **corrected Fisher** (fix `9da31ee`, deployed to the
live engine 2026-07-10 ~06:47 UTC before this build ran — the brief's
dependency is satisfied). Result: **VACUOUS — 0 trades in all 24 configs.**

> **BACKTEST ONLY — EXPLICITLY NOT CHALLENGE-RELEVANT.** This design has no
> stop: worst-case loss is unbounded by construction and the premise cannot
> run on the Propr account. Spot-capital context only. Nothing here trades
> anything, live or paper. SIMULATED caveats apply (idealized close fills,
> fees 0.075%/side, no funding/slippage, 5,000-bar 4H retention).

## Pre-registered design (per Zane's brief, verbatim where it decided)

- **Entry:** LONG when 4H Fisher ≤ −thr AND bias close > SMA(window);
  SHORT mirrored. One open trade at a time; entries/exits at bar close.
- **Exits, first-to-fire, individually logged:** (a) *reversion* — close
  beats entry by the round-trip fee cost (net-profitable, the literal
  "closed once profit hits"); (b) *Fisher-reversal* — Fisher back through
  ±1.5 (single pre-registered level; corrected 4H Fisher exceeds 2.0 on
  only 0.2% of bars, so a 2.0 exit would ~never fire); (c) *time cap* —
  holding-period ceiling, not a price stop.
- **No stop.** Sizing: fixed % of INITIAL capital (non-compounding) so
  worst-case $ is linear — 5%/10% are reporting columns (they scale the
  same trade list; not run axes), which also resolves the brief's open
  item 2.
- **Grid (stated up front): 24 runs** = bias TF {1D, 12H} × SMA {30, 50}
  (open item 1: both tested) × threshold {−2.0, −3.0} × cap {none, 14d,
  30d}. Within the 30–40 budget without cutting an axis.
- Data: frozen snapshots (4H 2024-03-27 → 2026-07-09, 5,000 bars; 1D/12H
  bias series). Causal SMA alignment via last-closed-bias-bar join.
  Machinery selfchecked (entry/reversion/fisher-reversal/time-cap/MAE/fee
  arithmetic on synthetic series).

## Results

### Entry-condition frequency (corrected 4H Fisher, 2.3 years)

| Threshold | Bars | Share |
|---|---|---|
| \|F\| ≥ 1.0 | 1,442 | 29.2% |
| \|F\| ≥ 1.5 | 296 | 6.0% |
| \|F\| ≥ 1.75 | 63 | 1.3% |
| **\|F\| ≥ 2.0** | **8** | **0.2%** |
| **\|F\| ≥ 3.0** | **0** | **0.0%** |

### Trades: **0, in every one of the 24 configs.**

Threshold −3.0 cannot fire (never reached on 2020s BTC data — corrected
ceiling observed 2.21). Threshold −2.0 has exactly 8 qualifying bars, and
**every one of them had the bias unanimously AGAINST the required
direction, under all four bias definitions (1D/12H × SMA30/50):**

| Bar (UTC) | Fisher | Entry needs bias | Actual bias (all 4 defs) |
|---|---|---|---|
| 2024-07-16 03:59 | +2.01 | DOWN | UP |
| 2024-07-27 11:59 | +2.11 | DOWN | UP |
| 2024-07-27 15:59 | +2.07 | DOWN | UP |
| 2025-06-25 07:59 | +2.15 | DOWN | UP |
| 2025-06-25 11:59 | +2.21 | DOWN | UP |
| 2025-06-25 15:59 | +2.06 | DOWN | UP |
| 2026-03-07 23:59 | −2.04 | UP | DOWN |
| 2026-03-08 03:59 | −2.10 | UP | DOWN |

### Worst-case table (given equal weight per the brief)

Vacuously empty — with zero entries there is no MAE, no time-to-revert
distribution, and no worst trade. **This is stated as the headline, not
buried:** the strategy's risk was never exercised because the strategy
never existed on this data.

## Findings (honest read)

1. **The premise is vacuous at the pre-registered thresholds — it doesn't
   even reach falsification.** Corrected 4H Fisher touches ±2.0 four bars
   a year; ±3.0 never. Zane's own market intuition ("rarely crosses 2–3")
   is precisely confirmed, and is exactly why a ±2/±3 entry cannot
   generate a testable sample, let alone a higher-frequency strategy.
2. **The deeper structural finding: 4H Fisher extremes are trend events,
   not counter-trend events.** All 8 extremes occurred with every SMA
   bias aligned WITH the Fisher direction — blow-off readings happen
   inside established trends (July-2024/June-2025 rallies, March-2026
   selloff), never as a dip against a still-standing opposing trend. The
   "washed-out dip in an uptrend" confluence did not occur once in 2.3
   years. Any Fisher-extreme strategy on this timeframe is therefore
   implicitly trading WITH the prevailing trend or not at all.
3. **Consequence for the higher-frequency goal:** post-fix, no
   Fisher-threshold design at conventional levels can be high-frequency —
   the events are too rare. The in-family lever is a LOWER threshold
   (±1.5 → 296 bars ≈ 2.4/week; ±1.25 → 727), which is a **new
   hypothesis needing its own pre-registration** — deliberately not run
   here (the anti-mining rule). Out-of-family, the genuinely
   higher-frequency paths remain the parked OI/liquidation Phase 2
   (event-driven cascades) and sub-4H signal families.
4. Open items from the brief: (1) SMA window — both 30 and 50 tested,
   answer moot at n=0; (2) sizing — fixed % of initial capital,
   non-compounding, stated above, also moot at n=0.

## Round 2 — threshold −1.5 (Zane's clarified intent, 2026-07-10)

Zane's correction to round 1: *"Fisher extremes are indeed trend events and
my intention was to trade the mean reversion within the trend. e.g. Trend
is UP, sell off occurs on LTF (4hr) hitting fisher extreme > −1.5 where a
long within the trend is made. Once that long returns profit, position is
closed. Rinse and repeat."* Round 1's entry logic already implemented
exactly this; the −2.0/−3.0 thresholds were the mismatch. His message is
the pre-registration for the −1.5 run round 1 flagged. Same grid minus the
threshold axis: **12 configs** (bias TF × SMA × cap), same exits, sizes as
reporting columns. |F| ≥ 1.5 = 296 bars (6.0%).

### Results (2024-03 → 2026-07, 2.28 years)

| Config (cap=none) | Trades | W–L | P&L (% of position) | P&L (% capital @5% / @10%) | Worst MAE (position) | ttr med/p90/max (days) |
|---|---|---|---|---|---|---|
| 1D/SMA30 | 36 | 35–1 | +12.74% | +0.64% / +1.27% | −15.3% | 0.3 / 5.0 / 11.8 |
| 1D/SMA50 | 34 | 33–1 | +11.56% | +0.58% / +1.16% | −15.3% | 0.3 / 3.8 / 11.8 |
| 12H/SMA30 | 20 | 20–0 | +11.97% | +0.60% / +1.20% | −11.7% | 0.3 / 5.0 / 10.5 |
| **12H/SMA50** | **31** | **31–0** | **+18.61%** | +0.93% / **+1.86%** | −11.7% | 0.3 / 5.0 / 10.5 |

Hold caps: **14d made everything worse** (converts the deepest trade into a
realized −12.50% time_cap loss and cuts 1D P&L from +12.74% to +9.11%);
**30d is identical to no-cap** — on this window every capped-off trade
would have reverted. Caps only destroyed value here.

### Worst-case table (equal weight, per the brief)

| Trade | Side | MAE (position) | Held | Outcome |
|---|---|---|---|---|
| 2024-07-14 | SHORT | **−15.3%** | 16.2d | **−8.82% realized** (fisher_reversal) — the one loss; erases ~25 average wins |
| 2025-01-15 | SHORT | −13.2% | 11.8d | +0.04% (rescued at breakeven) |
| 2025-09-30 | SHORT | −11.7% | 10.5d | +0.08% (rescued) |
| 2025-03-02 | SHORT | −10.7% | 1.7d | +0.13% |
| 2025-02-01 | LONG | −9.3% | 1.8d | +1.13% |

At 10% sizing these MAEs are −0.9% to −1.5% of capital sitting unrealized;
they scale linearly with size, and the tail is **unbounded** — no mechanism
exists to stop a dip that never bounces.

### Findings (honest read)

1. **The mechanism works as described — on this window.** Dips within
   trend reverted fast (median 0.3 days ≈ 2 bars; p90 ~5 days), the
   rinse-and-repeat is real, and the best cell nets +18.6% of position
   notional (~+8.2%/yr on deployed notional) with 31/31 wins.
2. **Ignore the win rate — it is ~100% by construction** (exit only on
   profit). The informative numbers are the MAE distribution and the
   single realized loss: −8.82% (one trade) vs ~+0.35–0.6% per win. The
   profit engine collects small bounces while periodically sitting 10–15%
   underwater for up to two weeks hoping. Four to five trades per config
   were hostages rescued at ~breakeven.
3. **Sized survivably, it doesn't move the needle: <1%/yr of capital at
   5–10% sizing.** Making it matter requires 50–100% sizing, at which
   point one 2022-style non-bouncing leg — unbounded by design — is
   account-ending. Expectancy was positive here because every 2024–26 dip
   eventually bounced: that is a regime property, not a strategy property.
4. **It is also not higher-frequency: 9–16 trades/yr**, same order as the
   trend system. Raising frequency means −1.25 (727 bars) or 1H Fisher —
   each a fresh pre-registration facing the same tail math.
5. **Observation (post-hoc, NOT a result):** every deep-MAE trade but one
   was a SHORT fading a rally; the long side (Zane's actual example)
   behaved better (worst long MAE −9.3%). A long-only variant is a
   plausible round 3 — flagged for fresh pre-registration, deliberately
   not run today.

## Round 3 — long-only, 12H bias, volume + exit axes (Zane's rules, 2026-07-10)

Rules: (1) **no shorts** — mean reversion within an UP trend only; (2) more
trade volume, strategy on the 4H-trigger/12H-bias frame. Pre-registered
axes, each mechanism-motivated: threshold {−1.0, −1.25, −1.5} (the volume
lever), exit {first_profit, atr_tp = entry+1×ATR(4H)} (first-profit
forfeits most of each bounce; the TP variant tests harvesting it), SMA
{30, 50}, no caps (round-2 evidence), no stop (design). 12 configs.

### Results (long-only, 12H bias, cap none, 2024-03 → 2026-07)

| Thr | Exit | SMA30: n / P&L(pos) / worstMAE | SMA50: n / P&L(pos) / worstMAE |
|---|---|---|---|
| −1.0 | first_profit | 47 / **+12.23%** / −16.6% | 49 / **−48.75%** / **−34.2%** |
| −1.0 | atr_tp | 33 / −9.79% / −27.5% | 33 / −34.59% / −34.2% |
| **−1.25** | **first_profit** | **17 / +6.66% / −16.5%** | **18 / +7.64% / −16.5%** |
| −1.25 | atr_tp | 15 / +10.73% / −16.5% | 17 / −1.16% / −26.0% |
| −1.5 | first_profit | 6 / +4.50% / −3.7% | 9 / +7.31% / −3.7% |
| −1.5 | atr_tp | 6 / +2.56% / −14.9% | 8 / −3.60% / −25.8% |

### Findings (honest read)

1. **The volume lever works but buys tail, and the −1.0 cell is a trap.**
   21 trades/yr achieved — and the two bias windows disagree by **61
   points** (+12.2% vs −48.8%). Shallow-dip entries fire into the starts
   of real downlegs; whether you survive depends on how fast the SMA
   flips DOWN. A cell whose twin config blows up is not a winner — it is
   parameter roulette. Do not deploy anything at −1.0.
2. **The robust region is −1.25 / first_profit:** positive on both SMA
   windows (+6.7%/+7.6% of position, 17–18 trades all-win, ~7.5
   trades/yr — 2.5× the −1.5 cadence), identical worst-MAE profile to
   round 2 (−16.5%, the hostage class). ~+3%/yr on deployed notional;
   at 10% capital sizing ≈ +0.3%/yr — still thin in capital terms.
3. **ATR take-profit rejected by evidence** (worse in 3 of 4 direct
   comparisons): waiting for the full bounce holds exposure long enough
   for Fisher-reversal losses to realize. The quick first-profit escape
   IS the strategy's working half.
4. **Round-2 recheck:** most of round 2's volume and P&L was actually the
   SHORT side (12h/SMA50 thr1.5: 31 trades combined → 9 long-only) —
   rallies-within-downtrends reach +1.5 more often than dips-within-
   uptrends reach −1.5 on this window. Long-only is cleaner but smaller.
5. **No robust winner exists in this family on this data.** The honest
   best is −1.25/first_profit — parameter-stable, all-win, hostage-prone,
   ~7.5 trades/yr, thin. Sequential rounds on the same window (r1→r2→r3)
   also accumulate selection risk: the only legitimate promotion path is
   a paper forward test of the named cell, exactly like tsmom30's.

## Round 4 — clean single-variable threshold sweep (2026-07-11)

Per Zane's Round 4 brief: everything frozen except the 4H Fisher entry
threshold. **Fixed:** long-only; 12H **SMA30** bias (the delegated pick —
Round 3's better-behaved window at the widest threshold, where SMA50's
−48.75% regime-lag blowup would swamp the per-threshold comparison; the
SMA50 view stays documented in Round 3); first-profit exit (ATR-TP already
rejected); no stop, no leverage, no hold cap; sizing = fixed % of initial
capital, non-compounding, P&L primary in % of position notional with 5%/10%
capital columns (identical to Rounds 2–3). Regression check: the three
cells overlapping Round 3 reproduce it exactly.

| Threshold | Trades | Total return (% notional) | Worst MAE | Median time-to-revert | p90 time-to-revert |
|---|---|---|---|---|---|
| −1.00 | 47 | +12.23% | −16.61% | 0.2d | 2.8d |
| −1.25 | 17 | +6.66% | −16.53% | 0.5d | 2.7d |
| −1.50 | 6 | +4.50% | −3.66% | 0.2d | 2.5d |
| −1.75 | 2 | +1.40% | −3.36% | 0.2d | 2.0d |

**The callout the round exists to answer:** yes — worst-case MAE improves
meaningfully between −1.25 and −1.50 (−16.5% → −3.7%), and it is **not** an
exit-type artifact (all four cells share the first-profit exit; Round 3's
drop was already within first-profit cells). The per-trade data attributes
the entire transition to **one identifiable episode**: the 2024-08-27 dip,
entered at Fisher −1.15 (thr −1.0 cell) / −1.33 (thr −1.25 cell), which sat
**−16.5/−16.6% underwater for 23.5 days** before a ~breakeven rescue
(+0.15%/+0.25%) — it is also both cells' max time-to-revert. A −1.50
threshold never qualifies for that episode, collapsing both the MAE and the
hold-time tail (max 2.5d).

**Honest caveat on reading −1.50 as "safe":** the tail difference is n=1
episode placement, not a structural guarantee — Round 2 already showed a
−15.3% MAE at ±1.5 (on the short side), and nothing prevents a future
slow-bleed dip from bottoming just beyond −1.5 with the same hostage
dynamics. The threshold trades frequency for episode-exclusion, linearly:
−1.0 buys 47 trades and the whole tail; −1.75 buys near-dormancy (2
trades) and a clean window. −1.25 vs −1.50 is a choice between +6.66% with
a 23-day −16.5% hostage and +4.50% without it — on this window.

## Round 6 — DCA add-triggers (2026-07-11)

**Named plainly up front: this is Martingale-adjacent** — every design adds
exposure into an adverse move. The 2024-08-27 hostage (−16.5%, 23.5 days)
is exactly the episode these designs would add into; whether that
multiplies the recovery or the loss is unknowable until it resolves. (No
Round 5 exists in this repo; per the brief, Round 6 builds on Round 4's
baseline — first-profit exit, NOT target exits.)

**Fixed:** base entry 4H Fisher ≤ −1.25, 12H SMA30 bias, long-only,
first-profit exit on the BLENDED position, no stop, **no leverage**
(explicitly out of scope), no cap. **Technical default, not policy: max 3
adds (4 tranches), equal tranches at the standard 5%/10%-of-initial-capital
sizing. Exposure arithmetic stated before any results: at 4 tranches, one
unstoppable position can commit 20% (at 5% tranches) to 40% (at 10%) of
capital.** Exits are evaluated before adds each bar; per-unit fees are
tranche-count invariant. Single-entry code path untouched (Round-4
regression re-verified exact: 17 / +6.66% / −16.53%).

Baseline for all comparisons: Round 4's −1.25 cell = 17 trades, **+6.66
units** (1 unit = % of one tranche's notional), worst MAE −16.53%.

| Design | Episodes | Tranches (1/2/3/4) | P&L (units) | Lump-sum control¹ | Worst-case exposure @10% | Avg-entry gain² | Worst MAE (units / deployed) | ttr med/p90/max | Rescue-dep³ |
|---|---|---|---|---|---|---|---|---|---|
| deeper-extreme | 17 (all win) | 15/2/0/0 | +8.34 | +7.46 → **beats +0.88** | 20% ($20k) | +0.63% | −16.5 / −16.5% | 0.5/2.7/**23.3d** | 3.0% |
| divergence | 17 (all win) | 12/2/2/1 | +9.43 | +10.19 → **loses −0.76** | **40% ($40k)** | +1.63% | −10.7 / **−7.9%** | 0.5/2.3/**2.5d** | 15.1% |
| confirmed-reversal | 17 (all win) | 13/4/0/0 | **+11.68** | +8.26 → **beats +3.42** | 20% ($20k) | +1.36% | **−26.9** / −13.4% | 0.5/2.7/21.3d | 7.2% |

¹ Same mean deployed capital (mean tranches × baseline +6.66) as a single
entry at tranche-1 price — the DCA-vs-lump-sum control.
² Mean improvement of blended entry vs tranche-1 price, multi-tranche
episodes only. ³ Share of P&L from episodes ever ≥5% underwater (deployed).

### 6.1 Deeper-extreme adds — under-tested, honestly

Added in only **2 of 17 episodes** (mean 1.12 tranches); the −2.25/−2.75
levels never fired (corrected 4H Fisher min is −2.21), and notably the
Aug-27 hostage itself **never reached −1.75** — the highest-risk trigger
largely failed to trigger. +0.88 units over lump-sum on n=2 add-events is
anecdote, not evidence. Per the brief's own standard: this design wasn't
really tested by this window.

### 6.2 Bullish-divergence adds — busiest, and loses to lump-sum

Most active (5 episodes multi-tranche, one 4-tranche episode = the full
40%-of-capital exposure case at 10% sizing). It added three tranches into
the Aug-27 hostage — and the blended entry cut the episode's max
time-to-revert from 23.3d to **2.5d** and its deployed MAE to −7.9%: DCA
"working" visually. But the control exposes the catch: deploying the same
average capital as a single entry would have returned **more** (+10.19 vs
+9.43 units). The extra tranches bought smoother optics, not better
returns, and 15.1% of its P&L is rescue-dependent. Add-gaps: 0.2–1.5d —
adds do cluster within episodes (min-gap guard is a justified follow-up).

### 6.3 Confirmed-reversal adds — the only design that beats its control

+11.68 units vs +8.26 control (**+3.42, a 41% improvement on the same
average capital**), with adds in 4 of 17 episodes at ~1-day spacing. The
trade-off stated up front in the brief showed up exactly as predicted: it
buys at worse prices than the extreme (avg-entry gain +1.36% < divergence's
+1.63%) but with confirmation — and it carried the round's worst
full-exposure MAE (−26.9 units: the Aug-27 hostage at 2× size for 21.3
days, −13.4% of deployed). At 10% tranches that episode sat −2.7% of
capital underwater in an unstoppable position.

### Round-6 honest read

1. **Only confirmed-reversal survives its own control.** Deeper-extreme
   barely fires (n=2); divergence is busier but strictly worse than
   sizing bigger at entry. If anything from this round advances, it is
   reversal-adds — on 4 add-events, in one regime, with the largest
   full-exposure tail of the three.
2. **The Martingale shape is visible in the numbers:** every design's
   worst episode is the same Aug-27 hostage; adds either missed it
   (deeper), smoothed it while diluting returns (divergence), or doubled
   into it and won this time (reversal). "This time" is the operative
   caveat — one non-bouncing dip converts the +3.42-unit edge into a
   multi-tranche unbounded loss.
3. n = 17 episodes, 2–5 add-events per design, one macro regime.
   SIMULATED. Nothing here is promotable without forward evidence; the
   named candidate for any future work is reversal-adds on the −1.25
   base.

## Reproduce

```powershell
python scripts/track4_mean_reversion.py --phase selfcheck
python scripts/track4_mean_reversion.py --phase run                                    # round 1 (thr 2.0/3.0)
python scripts/track4_mean_reversion.py --phase run --thresholds 1.5 --tag r2_thr15    # round 2
python scripts/track4_mean_reversion.py --phase run --long-only --bias-tfs 12h `
  --thresholds 1.0,1.25,1.5 --exit-modes first_profit,atr_tp --caps none --tag r3_long # round 3
python scripts/track4_mean_reversion.py --phase run --long-only --bias-tfs 12h --sma-windows 30 `
  --thresholds 1.0,1.25,1.5,1.75 --exit-modes first_profit --caps none --tag r4_sweep  # round 4
```

Machine-readable: `research/output/track4_results.json` (round 1),
`…_r2_thr15.json` (round 2), `…_r3_long.json` (round 3),
`…_r4_sweep.json` (round 4).
