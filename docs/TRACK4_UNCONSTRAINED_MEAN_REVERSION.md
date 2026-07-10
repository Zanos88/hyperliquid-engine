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

## Reproduce

```powershell
python scripts/track4_mean_reversion.py --phase selfcheck
python scripts/track4_mean_reversion.py --phase run
```

Machine-readable: `research/output/track4_results.json` (all 24 configs).
