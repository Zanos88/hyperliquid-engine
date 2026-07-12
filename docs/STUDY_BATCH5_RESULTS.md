# Study Batch 5 — Results (S-A … S-G)

Run 2026-07-12. Registration: docs/STUDY_BATCH5.md. S-F (methodology
retrofit + block-boot bars) is in docs/STUDY_BATCH5_SF.md; every kill
criterion below reports against S-F's block-boot bars. SIMULATED throughout;
frozen data; all cells reported regardless of outcome.

---

## S-A — Track 4 Round 5R: joint stop × target grid

**Verdict: Comp NULL CONFIRMED.** Adjudicates the review disagreement, and
the honest answer splits the difference: **targets DO turn several stopped
cells net-positive (Claude-review partially right), but NO stopped cell
clears its block-boot Sharpe bar (Grok-review right on the decisive
criterion).** The kill criterion — a stopped cell positive net of ~14 bps RT
AND clearing the S-F block-boot bar — is not met by any cell.

Base: long-only, 4H Fisher ≤ −1.25, 12H SMA30 bias, frozen (Rounds 3–4
window). Grid: exits {first_profit, +0.5R, +1.0R, +1.5R} × stops {none,
2.5×ATR, 3.5×ATR} = 12 cells. R vs the stop where one exists; no-stop cells
report R-equivalents vs 3.5×ATR.

| Stop | Target | n | W | Net R | Net % | PF | Sharpe | block-bar | worst MAE | kill? |
|---|---|---|---|---|---|---|---|---|---|---|
| none | first_profit | 17 | 17 | +1.54 | +6.66 | — | 0.45 | 1.05 | −16.5% | (no-stop) |
| none | +0.5R | 15 | 13 | +4.36 | **+20.73** | 4.31 | 0.55 | 1.05 | −16.5% | (no-stop) |
| none | +1.0R | 13 | 10 | +1.06 | +9.07 | 1.16 | 0.16 | 1.05 | −27.4% | (no-stop) |
| none | +1.5R | 12 | 9 | +2.98 | +18.16 | 1.44 | 0.32 | 1.04 | −27.4% | (no-stop) |
| 2.5×ATR | first_profit | 17 | 15 | −0.46 | +0.14 | 0.78 | 0.22 | 1.07 | −7.9% | ✗ |
| 2.5×ATR | +0.5R | 15 | 11 | +0.76 | +5.59 | 1.18 | 0.29 | 1.06 | −7.9% | ✗ |
| 2.5×ATR | +1.0R | 15 | 9 | +1.35 | +5.95 | 1.21 | −0.14 | 1.02 | −7.9% | ✗ |
| 2.5×ATR | +1.5R | 15 | 8 | +2.85 | +11.79 | 1.39 | 0.15 | 1.02 | −7.9% | ✗ |
| 3.5×ATR | first_profit | 17 | 16 | +0.44 | +2.10 | 1.43 | 0.35 | 1.09 | −7.9% | ✗ |
| 3.5×ATR | +0.5R | 15 | 11 | +0.97 | +4.47 | 1.23 | 0.10 | 1.04 | −7.9% | ✗ |
| 3.5×ATR | +1.0R | 15 | 9 | +1.53 | +6.93 | 1.25 | 0.22 | 1.01 | −7.9% | ✗ |
| **3.5×ATR** | **+1.5R** | 14 | 8 | **+3.46** | **+15.14** | **1.56** | 0.30 | 1.01 | −7.9% | ✗ |

**Findings:**
1. **Comp NULL stands, but the mechanism is now precisely characterized.**
   The best *stopped* cell (3.5×ATR / +1.5R) is genuinely attractive on
   point estimates — +3.46R, PF 1.56, win rate 8/14, worst MAE −7.9% (half
   the no-stop tail) — a real "comp-compliant Track 4" candidate. It fails
   only on the statistical bar: Sharpe 0.30 vs block-boot 1.01. At n=14 the
   positive net is not distinguishable from chance.
2. **Wide stop + far target is the right geometry** (monotone: +1.5R beats
   +1.0R beats +0.5R at both stop widths on net R; 3.5×ATR beats 2.5×ATR),
   which refines Track 4-Comp's "first-profit R-economics kill it" — a
   +1.5R target fixes the R-economics (avg win rises), just not enough to
   clear a chance bar at this sample size.
3. **Both reviews were partly right, as registered:** targets lift stopped
   cells to net-positive (Claude), but none survives the significance bar
   (Grok). The decisive kill criterion is the bar → NULL CONFIRMED.
4. Aside (not the S-A question): the no-stop / +0.5R cell (+20.73%, PF 4.31)
   is the strongest net cell overall — the +0.5R target materially improves
   the no-stop Track 4 design over first-profit — but it is not comp-
   compliant and does not bear on the stop adjudication.

**Conclusion #3 (Comp NULL) stands as written.** The 3.5×ATR/+1.5R cell is
logged as the least-weak comp-compliant candidate for a future forward test
should Zane want one, explicitly not promoted here.

---

## S-D — Reversion asymmetry diagnostic (not a strategy)

**Verdict: DIRECTIONAL support, within noise — but it structurally justifies
long-only.** Conditional on 4H Fisher crossing ±{1.0, 1.25, 1.5}, forward
{6, 24, 72}-bar return means, long side (oversold, Fisher ≤ −X) vs short
side (overbought, Fisher ≥ +X), with stationary block-boot 95% CIs.

| \|F\|≥ | H (bars) | LONG n / mean% (CI) | SHORT n / mean% (CI) | rev_long | rev_short | asym |
|---|---|---|---|---|---|---|
| 1.0 | 6 | 596 / −0.09 (−0.48,+0.28) | 845 / +0.13 (−0.18,+0.42) | −0.09 | −0.13 | +0.04 |
| 1.0 | 24 | 596 / +0.42 (−0.45,+1.30) | 844 / −0.13 (−0.86,+0.62) | +0.42 | +0.13 | +0.29 |
| 1.0 | 72 | 596 / +0.62 (−1.50,+2.93) | 828 / +0.02 (−1.53,+1.63) | +0.62 | −0.02 | +0.64 |
| 1.25 | 6 | 275 / −0.18 (−0.95,+0.52) | 452 / +0.20 (−0.14,+0.55) | −0.18 | −0.20 | +0.02 |
| 1.25 | 24 | 275 / +0.26 (−0.84,+1.36) | 452 / +0.06 (−0.78,+0.97) | +0.26 | −0.06 | +0.32 |
| 1.25 | 72 | 275 / +0.40 (−2.05,+2.71) | 438 / +0.51 (−1.41,+2.54) | +0.40 | −0.51 | +0.91 |
| 1.5 | 6 | 87 / −0.35 (−1.49,+0.81) | 209 / +0.36 (−0.01,+0.75) | −0.35 | −0.36 | +0.02 |
| 1.5 | 24 | 87 / +0.28 (−1.53,+1.83) | 209 / +0.67 (−0.52,+1.80) | +0.28 | −0.67 | +0.95 |
| 1.5 | 72 | 87 / −0.40 (−2.80,+1.73) | 201 / +1.23 (−1.31,+3.97) | −0.40 | −1.23 | +0.83 |

(reversion_long = +mean after oversold; reversion_short = −mean after
overbought; asymmetry = rev_long − rev_short, all %.)

**Findings:**
1. **Asymmetry sign is consistent (positive in 9/9 cells) but every effect
   size is within its block-boot CI of zero.** So the "reversion is stronger
   after negative extremes" claim is *directionally supported* in our sample,
   not statistically established. Honest label: suggestive, underpowered.
2. **The short side is systematically adverse at longer horizons** — after
   overbought, price tends to keep RISING (short_mean positive → rev_short
   negative, reaching −1.23% at |F|≥1.5/H=72). Shorting BTC overbought
   extremes in this sample fades a continuing uptrend. This upgrades Track
   4's long-only from "an empirical accident of Round 2's short blowup" to
   a **structural property visible across the full conditional distribution**
   — the single most useful output of this diagnostic.
3. **Long-side reversion peaks near H≈24 bars (~4 days)** (+0.26 to +0.42%),
   matching Track 4's observed median hold — the design is entered at the
   right horizon even though the edge is thin.

No trading rule produced (by design). Informs S-A's interpretation: the
long-only restriction is justified; the thin-but-positive long-side
reversion at 24 bars is exactly the effect S-A's cells monetize (and which
survives net but not the Sharpe bar).

---

## S-B — Breakout wide-stop / time-invalidation re-test

**Verdict: NULL — and a textbook demonstration of why S-F added Deflated
Sharpe alongside the block-boot bar.** One cell (time-invalidation / 2R)
*mechanically clears the block-boot Sharpe bar* (1.13 vs 1.07) but **DSR
rejects it (0.657 < 0.95)**, and forensics expose the pass as bull-market
beta, not breakout alpha. The archetype stays closed — now with the geometry
objection genuinely tested (a stronger null than the original 0/24).

4H trigger, 1D Fib-S/R HTF bias, volume-confirmed (mult 2.0, 20th-pct floor).
6 cells = stops {2.0×ATR, 3.0×ATR, time-invalidation (exit if not +0.5R in
12 bars, no price stop)} × targets {2R, trail 2.5×ATR}.

| Stop | Target | n | W | Net R | Net % | PF | Sharpe | block-bar | DSR | max hold | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2.0×ATR | 2R | 37 | 16 | +8.82 | +18.18 | 1.40 | 0.58 | 1.05 | 0.33 | 10d | NULL |
| 2.0×ATR | trail 2.5×ATR | 37 | 14 | −6.42 | −25.15 | 0.66 | 0.25 | 1.05 | 0.18 | 7d | NULL |
| 3.0×ATR | 2R | 30 | 13 | +7.77 | +19.30 | 1.44 | 0.17 | 1.05 | 0.15 | 16d | NULL |
| 3.0×ATR | trail 2.5×ATR | 37 | 14 | −4.50 | −26.31 | 0.65 | 0.29 | 1.06 | 0.19 | 7d | NULL |
| **time-inval** | **2R** | **14** | **13** | **+24.01** | **+59.06** | **21.24** | **1.13** | 1.07 | **0.66** | **162d** | **NULL (beta)** |
| time-inval | trail 2.5×ATR | 38 | 14 | −5.77 | −22.40 | 0.69 | 0.26 | 1.05 | 0.18 | 7d | NULL |

**Findings:**
1. **The registered prediction is confirmed on net R — but the mechanism
   invalidates it.** Time-invalidation/2R nets +24R (vs +8.8R for the best
   price-stop cell), and PF 21.24 with 13/14 wins looks spectacular. The
   forensics: every winner exits at *exactly* +2R, the single loss is the
   one time-invalidated trade, worst MAE **−23.9%** (no price stop), and
   **max hold 162 days** (another at 40 days). The 2R target with no stop
   and no time-cap-once-+0.5R-progress-is-made turns winners into
   multi-month LONG HOLDS that capture bull-market drift until price
   drifts +2R. It is buy-and-hold beta wearing a breakout costume, not a
   continuation edge.
2. **DSR is the honest arbiter and it rejects the cell (0.657).** The
   block-boot bar (which resamples returns but keeps the long-hold position
   fixed) is nearly fooled because a persistent-long position's resampled
   Sharpe stays near buy-and-hold's; Deflated Sharpe — correcting for the 6
   trials and the return non-normality — catches it. This validates S-F's
   decision to report BOTH: the bar alone would have produced a false
   positive here.
3. **No cell survives on both criteria** → the breakout archetype is closed
   with the geometry objection actually tested. The tight-stop 0/24 null and
   this wide-stop/time-invalidation null together bracket the geometry space:
   BTC breakouts of recent swing levels do not continue reliably enough to
   pay for either a tight stop (whipsaw) or a wide/no stop (the "edge"
   collapses to holding beta).

**Registered kill criterion (positive net + block-boot bar):** literally met
by one cell; but with S-F's DSR in the standard report, that cell fails, and
its mechanism is beta. Substantive verdict: **NULL.**
