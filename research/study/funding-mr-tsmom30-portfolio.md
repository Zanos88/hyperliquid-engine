# TSMOM30 + Funding MR Portfolio Blend

**Status:** Backtest-verified, PR ready  
**Date:** 2026-07-18  
**Author:** Hermes Agent (via btc-signal-bot study)

## What

A portfolio strategy that combines two low-correlation signals on 1D BTC perps:

| Signal | Logic | Exposure | Sharpe |
|---|---|---|---|
| TSMOM30 | Price > 30-bar trailing close | ~52% bars | 0.77 |
| Funding MR | Long when funding ≤ 30th percentile (BEAR) | ~5% bars | 1.00 |

## How

- Run TSMOM30 at **full size (1x)** at all times as the core trend-following signal
- When funding hits the bottom 30th percentile ("BEAR" regime — shorts are crowded and expensive), **ADD the Funding MR signal** at up to 1x
- Net position: 1.0x during normal periods, **up to 2.0x** during crowded-short overlap events
- For 1x-max leverage setups: scale both signals to 0.5x each during overlap

## Backtest Results

On 1D candles (Jul 2020 – Jul 2026, 2150 bars, eval ~1780 bars):

| Variant | Sharpe | AnnRet | MaxDD | NetMult |
|---|---|---|---|---|
| TSMOM30 baseline | 0.77 | 34.50% | 0.633 | 3.03x |
| Funding MR baseline | 1.00 | 11.44% | 0.121 | 1.50x |
| SMA50 baseline | 0.71 | 31.93% | 0.878 | 2.82x |
| **TSMOM30 + 100% FundMR overlap** | **1.03** | **49.38%** | **0.633** | **4.48x** |
| 50/50 equal-weight | 0.98 | 22.43% | 0.317 | 2.13x |
| Triple (33/33/33) | 0.89 | 25.52% | 0.503 | 2.34x |

MaxDD unchanged from TSMOM30 baseline because the Funding MR signal has **zero drawdown alignment** with TSMOM30's worst drawdown events.

## Why This Works

1. **Low signal correlation** — TSMOM30 (trend-following, momentum) and Funding MR (mean-reversion, crowded-short) profit in different market conditions
2. **Crowded-short events are rare but high-alpha** — only 5% of bars see funding ≤ 30th percentile
3. **When both fire, they fire in the same direction** — during bear-funding (cheap shorts), BTC tends to bounce; TSMOM30 confirms the uptrend
4. **No incremental drawdown** — the overlap bars don't coincide with TSMOM30's worst periods

## Files

- `strategy/portfolio_blend.py` — Strategy module with `portfolio_positions()` and convenience variants
- `scripts/portfolio_combination.py` — Portfolio blend study (runs in ~5s)
- `scripts/funding_mr_deepdive.py` — Individual trade trace for Funding MR
- `scripts/funding_custom_thresholds.py` — Threshold sensitivity exploration
- `scripts/regime_gated_study.py` — Original regime-gating study (TSMOM30 × Regime labels)

## To Run

```bash
cd /opt/data/repos/btc-signal-bot
source .venv/bin/activate
python scripts/portfolio_combination.py
```

## Next Steps

- [ ] Deploy to Prod channel monitor cron (tomorrow)
- [ ] Wire live funding data from exchange API
- [ ] Add 4H timeframe variant for faster signals
- [ ] Forward-test against 2026 H2 live data
- [ ] Calibrate position sizing (1x vs 2x max)
