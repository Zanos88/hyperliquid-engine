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
