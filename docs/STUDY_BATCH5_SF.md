# Study Batch 5 — S-F: Methodology Retrofit (results)

Run 2026-07-12. Registration: docs/STUDY_BATCH5.md. Machine-readable:
`research/output/batch5_sf.json`. **Headline: every existing verdict SURVIVES
the block-bootstrap retrofit unchanged — no tournament panel or Track 4 cell
clears its new bar, and no single cell survives Deflated-Sharpe deflation.
The one new, positive result is at the POOLED level: the common trend effect
across the 7 assets is significantly > 0 (Sharpe ~0.59, P>0 = 99.7%), which
is Bayesian support for "trend as risk management" as an aggregate property,
not a per-specification edge.**

## What the block-bootstrap null does and does not represent

Per rep: the asset RETURN series is stationary-block-resampled (Politis–
Romano, mean block ~20 days), each variant's Sharpe recomputed on
`position[i-1] · resampled_return[i]` with positions held fixed, and the
family-max over the variant set taken; the 95th percentile across 10,000
reps is the bar. **It preserves** the real return distribution and the
within-block autocorrelation of returns; **it deliberately breaks** the
relationship between the resampled path and the original signal timing.
So it tests exactly one thing: *"could this Sharpe plausibly arise from
generic market dependence (fat tails, volatility clustering, momentum in
the return process itself) rather than from genuine timing skill?"* It is
**not** a claim about live tradeability, capacity, regime shifts, or
out-of-sample stability — those are separate questions the forward tests
answer. Observed and null Sharpes are computed identically (same formula,
same fees; only the return sequence differs), so the comparison is fair.

## 1. Tournament re-report — old (shift-null) vs new (block-boot) bars

Regression check first: recomputed observed Sharpes reproduce the tournament
doc exactly (BTC-1d tsmom30 **0.77**, 12H sma200 **0.91**, breadth tsmom30
**0.78**), so the bars below are comparable to the originals.

| Panel | Best variant | Observed Sharpe | OLD shift bar | OLD verdict | NEW block bar | NEW verdict | DSR |
|---|---|---|---|---|---|---|---|
| BTC 1D | tsmom30 | 0.77 | 1.40 | NULL | **1.399** | **NULL** | 0.54 |
| BTC 12H | sma200 | 0.91 | 1.59 | NULL | **1.704** | **NULL** | 0.57 |
| 7-asset breadth | tsmom30 | 0.78 | 2.05 | NULL | **1.425** | **NULL** | — |

The block-boot bars land essentially on top of the old shift bars (BTC-1d
1.399 vs 1.40) or higher (12H 1.70 vs 1.59); breadth's bar drops (2.05 →
1.43) but the observed 0.78 is still well under it. **No verdict changes.**
Deflated Sharpe < 0.95 on every panel — no single specification survives
correction for the number of variants tried. The retrofit *hardens* the
program's tournament conclusion rather than moving it.

## 2. Track 4 −1.25 robust cell

Sharpe **0.46** (4H bars) vs block-boot bar **1.112** → **NULL** by Sharpe;
DSR 0.097. This is consistent with, not contradictory to, Track 4's prior
status: its documented value was in *% notional with MAE-managed holds and
~100%-by-construction win rate*, never a high Sharpe — a 0.46 Sharpe on 4H
bars does not clear a chance bar. The block bootstrap confirms Track 4 is
not a Sharpe edge; S-A adjudicates whether ANY stop/target variant of it is.

## 3. Live engine (4h/1h fib-extension) — PENDING (underpowered)

8 corrected trades (docs/CORRECTED_BASELINE_4H1H.md), total **+2.86R**, mean
**+0.357R/trade**. An iid bootstrap 95% CI on mean R is **(−1.14, +1.82)** —
it spans zero. At n=8 the trade sample is below any Sharpe-bar / DSR minimum,
so the honest verdict is **PENDING**: the live forward test (running, paper)
is the only instrument that can resolve it. This restates, with a CI, what
the program already held — the +2.86R backtest is directional, not proven.

## 4. Effective-bets basis (ends the "correlated crypto" objection)

| Set | Avg pairwise corr | N_eff (participation ratio) | N_eff (equicorrelation) |
|---|---|---|---|
| 7 assets (daily returns) | 0.65 | **1.95** | 1.42 |
| 7 trend-strategy streams (BTC 1D) | 0.76 | **1.54** | 1.25 |

Seven crypto assets act as ≈ **1.5–2 independent bets**, and the seven trend
rules as ≈ **1.5**. This is the quantitative reason breadth did not buy the
power the futures literature promises, and why the family-max multiplicity
correction is milder than "7 independent tries" would imply. One line, and
the objection is closed.

## 5. Hierarchical pooling — the one genuinely new positive result

Per-asset tsmom30 annualized Sharpes {BTC…LINK} partial-pooled (normal-normal,
DerSimonian–Laird τ):

- **Common trend effect: Sharpe 0.589, SD 0.217, 95% CI [0.164, 1.014], P(>0) = 99.7%.**

Pooling across assets — which no single-asset family-max bar can do — finds
the common trend effect **significantly positive**, even though no individual
asset/panel clears its own multiplicity-adjusted bar. The two facts are
consistent: each asset is individually underpowered (N_eff ≈ 2), but the
shared direction is real once information is combined. This is precisely the
"trend as risk management" claim the program has carried as its surviving
directional result — now with Bayesian support rather than only a
descriptive "21/21 cells beat buy-and-hold." **It does not overturn the
per-specification NULLs** (no tradeable single cell clears its bar); it
elevates the aggregate claim from "suggestive" to "supported."

## Verdicts (S-F)

| Item | Old verdict | New verdict |
|---|---|---|
| Trend tournament (all 3 panels) | NULL (shift bar) | **NULL (block bar)** — unchanged, hardened |
| Track 4 −1.25 (as a Sharpe edge) | thin/positive-notional | **NULL by Sharpe** |
| Live engine (+2.86R, n=8) | directional | **PENDING** (CI spans 0; forward test arbiter) |
| Common trend effect (pooled) | descriptive only | **POSITIVE** (Sharpe 0.59, P>0 99.7%) — new |

These bars are what S-A / S-B / S-C report against.

## Reproduce

```powershell
python scripts/blockstats.py              # selftest
python scripts/study_batch5.py --phase sf
```
