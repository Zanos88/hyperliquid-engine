# Trend Engine — No-Stop Patient-Hold Accumulation Variant

Run 2026-07-12. Spot-capital accumulation framing, **EXPLICITLY NOT the
Propr/comp account** (same framing as Track 4). Brief:
`TREND_ENGINE_NO_STOP_TEST.md`. Machine-readable:
`research/output/trend_no_stop.json`.

> **SIMULATED — not live performance, not comp-relevant.** Idealized touch/
> close fills, no slippage/funding, taker 0.075%/side. Frozen 4H/1H BTC
> snapshots (`research/data/BTC_{4h,1h}_snapshot.json`), window
> **2025-12-12 → 2026-07-09** (~209 days). **n = 8 resolved trades — this is
> attribution, not statistics.** The brief's rule is honored: these are the
> variant's OWN numbers, NOT the +2.86R result plus Track 4's drawdown
> profile, and are not blended with either.

## Verdict up front

**Different-shaped, and NOT a promotable edge. NULL / interesting-but-
unproven.** Removing the price stop and holding the trend engine's real
entries to *first profit or a 4H bias flip* produced **+5.70R vs the stopped
baseline's +2.86R** on the same 8 entries — but the entire +2.84R improvement
is (a) two shorts that snapped back to profit within ~2 hours instead of
stopping out, in a chop-down window that was kind to shorts (7 of 8 trades are
shorts), and (b) an exit asymmetry that keeps losers open while banking
winners early. The headline **overstates the case**: in R — the unit an
R:R-gated strategy is actually sized in — the worst trade went **−5.57R
underwater** and was force-flattened at **−4.34R**, versus the **−1R** a stop
would have capped. The "shallow −1.15% worst MAE" is a window artifact and a
unit illusion, not evidence of safety.

**Is the stop costing us or protecting us?** *Genuinely mixed*, not "the stop
was costing us." Of the 4 originally-stopped losers, 2 recovered fast (stop
cost ~+8.3R by cutting them early) and 2 ran deeper to a bias-flip exit (stop
would have protected, saving ~3.9R and, on the worst, ~3.3R).

**Track 4 rediscovered?** *Distinct in mechanism, same epistemic place.*
Unlike Track 4's unbounded no-stop (worst MAE −16.5%, holds to 23–66 days),
the 4H bias-flip is a catastrophe brake that capped the worst realized loss at
−4.34R. **But that brake was never stress-tested** — nothing was held long
(median time-to-first-profit **0.04 days ≈ 1 hour**; max hold across all 8
trades **0.3 days**). The failure mode that killed Tracks 3/4 — a trend
pinning the position offside for weeks — simply did not occur in this sample.
The bounded tail is *asserted, not demonstrated*.

## Cross-check: the stopped baseline reproduces exactly

The variant is only meaningful if the stopped run on the frozen snapshot
reproduces the corrected live-config baseline. It does, to the decimal:

| | `docs/CORRECTED_BASELINE_4H1H.md` (live fetch 2026-07-10) | **Stopped run on frozen snapshot** |
|---|---|---|
| Trades | 8 | **8** |
| W–L | 4–4 | **4–4** |
| Net | +2.86R | **+2.86R** |
| Profit factor | 1.43 | **1.43** |
| Max drawdown | 3.72R | **3.72R** |
| Suppressed by R:R gate | 87 | **86** (1-bar window edge) |

Identical entries by construction → the trade-by-trade reconciliation below is
apples-to-apples (only the exit mechanism differs).

## Patient-hold variant — its own numbers (MAE-first)

| Metric | Value |
|---|---|
| Trades / resolved / unresolved | 8 / 8 / 0 |
| Wins (net>0) | 6 (75%) |
| **Net** | **+5.70R** (avg +0.71R/trade) |
| Exit reasons | 6 reversion, 2 bias_flip, 0 unresolved |
| **Worst MAE (%)** | **−1.15%** |
| **Worst MAE (R)** | **−5.57R** ← the honest tail |
| Time-to-first-profit (days) | median 0.04 / p90 0.17 / max 0.17 |
| Deepest hostage | 2026-04-30 SHORT, bias_flip, MAE −1.15% / **−5.57R**, realized **−4.34R**, held 0.3d |

The **% vs R split is the whole story on risk.** Because the R:R≥2 gate admits
tight-stop setups (far target, close structural stop), a −1.15% adverse move
on the 04-30 short is −5.57R. In price the hold looks placid; in the strategy's
own risk unit it took a **−5.6R excursion and a −4.3R realized loss on one
trade** — 4× the −1R the stop would have enforced. **Both must be reported;
the % alone is misleading.**

## Trade-by-trade reconciliation (same 8 entries, exit swapped)

| # | Entry (UTC) | Dir | Stopped exit / R | Patient exit / R | Held | MAE %/R | Δ R | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | 2026-01-08 03:59 | SHORT | stop **−1.49** | reversion **+2.95** | 0.1d | −0.43% / −1.38R | **+4.44** | help |
| 2 | 2026-01-19 18:59 | SHORT | target +2.17 | reversion +0.76 | 0.2d | −0.34% / −0.65R | −1.41 | hurt |
| 3 | 2026-03-17 23:59 | SHORT | stop −1.46 | **bias_flip −2.74** | 0.2d | −1.05% / −3.20R | −1.28 | hurt |
| 4 | 2026-03-18 10:59 | SHORT | target +2.39 | reversion **+4.41** | 0.0d | −0.17% / −0.64R | +2.02 | help |
| 5 | 2026-03-19 11:59 | SHORT | target +1.96 | reversion +1.99 | 0.0d | 0.0% / 0.0R | +0.03 | match |
| 6 | 2026-03-22 19:59 | SHORT | stop **−1.99** | reversion **+1.88** | 0.1d | −0.45% / −2.95R | **+3.87** | help |
| 7 | 2026-04-30 04:59 | SHORT | stop −1.73 | **bias_flip −4.34** | 0.3d | −1.15% / **−5.57R** | −2.62 | hurt |
| 8 | 2026-05-24 22:59 | LONG | target +3.01 | reversion +0.81 | 0.0d | −0.0% / −0.01R | −2.21 | hurt |

### What the stop actually did (the brief's core question)

| Group | Stopped | Patient | Δ | Reading |
|---|---|---|---|---|
| **4 stopped losers** (1,3,6,7) | −6.67R | −2.25R | **+4.42R** | Net better — but split 2 recovered fast (1,6: stop *cost* +8.3R swing) vs 2 deepened (3,7: stop would have *protected* −3.9R) |
| **4 target winners** (2,4,5,8) | +9.53R | +7.96R | **−1.57R** | *Worse* — first-profit under-captures the clean winners (trade 8: +0.81R vs the +3.01R the target took) |

## Honest read

1. **n=8; two trades carry the result.** The +2.84R improvement is
   effectively trades 1 and 6 — two shorts that reverted to profit within ~2
   hours rather than stopping out — in the same Jan–Mar 2026 chop-down window
   that was kind to shorts. Drop those two and the patient variant *loses* to
   the stopped baseline. This is the identical regime property flagged for
   Track 4 and the breakout no-stop study: every 2024–26 dip/whipsaw
   eventually bounced.

2. **First-profit is the wrong exit for a trend engine — it inverts the
   edge.** The trend engine's premise is riding a directional move to a
   *structural target*; exiting at the first green close cuts winners off at
   the knees (−1.57R across the four clean winners). Pairing "no stop" with
   "first profit" means you **keep the losers and cut the winners** — the exact
   opposite of "cut losses, let winners run." That the net still came out ahead
   is a regime accident, not a design virtue. (Echoes S-A: first-profit
   under-captures.)

3. **The bias-flip brake is real but unproven.** It genuinely distinguishes
   this from Track 4's unbounded hold — the worst realized loss was −4.34R, not
   an open-ended hostage. But with a median hold of ~1 hour and a max of 0.3
   days, **the brake was never called upon under a sustained adverse trend.**
   Its protective value is untested here; on 4H it may also be twitchy
   (a brief flip to NEUTRAL force-flattens), which could just as easily cut
   good trades prematurely — trade 3/7's bias_flip losses may be exactly that.

4. **The R-tail is the discipline check.** A reviewer skimming "worst MAE
   −1.15%" would conclude the no-stop hold is safe. In R it is not: −5.57R on a
   single trade, on n=8, with the brake untested. Report both, lead with
   neither in isolation.

## Verdict

**NULL as a promotable strategy; no forward-test candidate.** The +5.70R is
in-sample real but regime-flattered, exit-asymmetry-flattered, and n=8; the
stop still does large protective work in R; first-profit is structurally the
wrong exit for trend entries; and the bias-flip brake is asserted, not
demonstrated. Nothing here supersedes the stopped live config or the running
dry-run forward test as the arbiter.

**One idea worth a purpose-built future test** (not supported by this run):
**4H-bias-flip invalidation as a softer catastrophe brake than a hard price
stop**, paired with a *let-winners-run* exit (structural/trailing target, not
first-profit), on a window that actually contains a sustained adverse trend.
That is a different experiment; this one does not license it.

## Reproduce

```powershell
python scripts/trend_no_stop.py --selfcheck
python scripts/trend_no_stop.py --phase run
```
