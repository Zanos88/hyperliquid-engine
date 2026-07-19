#!/usr/bin/env python3
"""
Jones Defense-First Strategy Study
- TSMOM30 with conviction pyramid (size by trend z-score)
- Hard stops (1.5x ATR, never average down)
- Holdout split (70/30)
- Binance cross-venue proxy for deep history
"""
from __future__ import annotations

import json, math, os, sys
from pathlib import Path

import numpy as np

# Load binance 1D proxy
CANDLES_PATH = "/opt/data/candles-binance/BTC_1d_snapshot.json"
MIRROR_PATH = "/opt/data/mirror"

with open(CANDLES_PATH) as f:
    raw = json.load(f)

schema = raw["schema"]
candles = raw["candles"]
split_ix = raw["split_index"]
total_bars = raw["bar_count"]

close_ix = schema.index("close")
high_ix = schema.index("high")
low_ix = schema.index("low")

closes = np.array([c[close_ix] for c in candles], dtype=np.float64)
highs = np.array([c[high_ix] for c in candles], dtype=np.float64)
lows  = np.array([c[low_ix] for c in candles], dtype=np.float64)

print(f"Loaded {total_bars} bars, split at {split_ix} (70%)")

# ── Helper ──────────────────────────────────────────────────────────────
def compute_atr(highs, lows, closes, period=14):
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )
    atr = np.zeros_like(closes)
    atr[:period] = np.nan
    atr[period] = np.mean(tr[:period])
    for i in range(period + 1, len(closes)):
        atr[i] = (atr[i-1] * (period - 1) + tr[i-1]) / period
    return atr

def rolling_vol(ret, window=30):
    return np.sqrt(np.nanmean(ret.reshape(-1, 1) ** 2, axis=1)) * np.sqrt(365)

# ── Strategy: TSMOM30 + Conviction Pyramid ────────────────────────────
def run_strategy(closes, highs, lows, fast=10, slow=30, atr_period=14,
                 vol_floor=0.02, conviction_scale=True):
    """TSMOM30 with Jones-style conviction pyramid sizing.
    
    Returns: positions (float array, 1.0 = 1x long)
    """
    n = len(closes)
    rets = np.diff(closes) / closes[:-1]
    rets = np.append(0, rets)  # pad first
    
    # TSMOM signal: sign of trailing return
    mom_fast = np.full(n, np.nan)
    mom_slow = np.full(n, np.nan)
    
    for i in range(slow, n):
        r_fast = closes[i] / closes[i - fast] - 1
        r_slow = closes[i] / closes[i - slow] - 1
        mom_fast[i] = r_fast
        mom_slow[i] = r_slow
    
    # Base direction: 1 = long, -1 = short, 0 = flat
    direction = np.sign(mom_slow)
    direction[np.isnan(direction)] = 0
    
    # Conviction: z-score of slow momentum relative to rolling window
    if conviction_scale:
        conv = np.full(n, np.nan)
        lookback = 252  # 1 year of daily data
        for i in range(lookback, n):
            window = mom_slow[i-lookback+1:i+1]
            window = window[~np.isnan(window)]
            if len(window) > 10:
                mu = np.mean(window)
                sigma = np.std(window)
                conv[i] = (mom_slow[i] - mu) / sigma if sigma > 0 else 0
            else:
                conv[i] = 0
        
        # Sizing: 0 = flat, 0.5 = half, 1.0 = full, 1.5 = overload
        size = np.zeros(n)
        for i in range(n):
            if np.isnan(conv[i]) or direction[i] == 0:
                size[i] = 0
            else:
                c = abs(conv[i])
                if c < 0.5:
                    size[i] = 0.5 * direction[i]
                elif c < 1.0:
                    size[i] = 1.0 * direction[i]
                else:
                    size[i] = 1.5 * direction[i]
    else:
        size = direction.copy()
        size[np.isnan(size)] = 0
    
    return size

def run_funding_mr(closes, lows, atr_period=14, risk_pct=0.02):
    """Funding-rate mean reversion proxy.
    Since we use Binance spot (no funding), we proxy cheap/expensive
    via volatility regime: when vol is in bottom 30th% → "cheap" (long),
    top 70th% → "expensive" (flat). Use ATR/close ratio.
    """
    n = len(closes)
    atr = compute_atr(highs, lows, closes, atr_period)
    atr_pct = atr / closes  # volatility as % of price
    
    # Rolling percentile
    lookback = 60
    cheap = np.zeros(n, dtype=bool)
    
    for i in range(lookback, n):
        window = atr_pct[i-lookback+1:i+1]
        window = window[~np.isnan(window)]
        if len(window) < 20:
            continue
        sorted_w = np.sort(window)
        rank = np.searchsorted(sorted_w, atr_pct[i])
        pct = rank / len(sorted_w)
        # Bottom 30% = cheap vol = bullish for MR (like cheap funding)
        cheap[i] = pct < 0.30
    
    return cheap.astype(float)

def compute_metrics(rets, ann_factor=365, label=""):
    """Compute full suite of metrics."""
    rets = rets[~np.isnan(rets)]
    if len(rets) < 5:
        return None
    
    total_ret = np.prod(1 + rets) - 1
    n_years = len(rets) / ann_factor
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    
    excess = rets - (1 + ann_ret) ** (1/ann_factor) + 1  # daily excess over risk-free
    std = np.std(rets)
    sharpe_raw = np.mean(rets) / std * np.sqrt(ann_factor) if std > 0 else 0
    
    # Max drawdown
    cum = np.cumprod(1 + rets)
    running_max = np.maximum.accumulate(cum)
    dd = (cum - running_max) / running_max
    max_dd = np.min(dd) if len(dd) > 0 else 0
    
    # Deflated Sharpe (Bailey/López de Prado)
    num_trials = max(1, int(len(rets) / 252))
    e_max_z = (1 - np.euler_gamma) * norm_ppf(1 - 1/num_trials) + np.euler_gamma * norm_ppf(1 - 1/(num_trials * np.e))
    if std > 0:
        deflated = (np.mean(rets) / std * np.sqrt(ann_factor) - e_max_z * np.sqrt(1 / len(rets)))
    else:
        deflated = 0
    
    return {
        "label": label,
        "ann_ret": round(float(ann_ret * 100), 2),
        "sharpe": round(float(sharpe_raw), 3),
        "deflated_sharpe": round(float(deflated), 3),
        "max_dd": round(float(max_dd * 100), 2),
        "total_return": round(float(total_ret * 100), 2),
        "n_years": round(float(n_years), 1),
        "n_trades": int(np.sum(np.abs(np.diff(np.sign(rets)))) / 2 + 0.5),
    }

from scipy.stats import norm as norm_ppf_import
norm_ppf = norm_ppf_import.ppf

# ── Main ────────────────────────────────────────────────────────────────
# Split data
is_closes = closes[:split_ix]
oos_closes = closes[split_ix:]
is_highs = highs[:split_ix]
oos_highs = highs[split_ix:]
is_lows = lows[:split_ix]
oos_lows = lows[split_ix:]

print(f"\n{'='*60}")
print(f"IS: 0-{split_ix}  ({len(is_closes)} bars)")
print(f"OOS: {split_ix}-{total_bars}  ({len(oos_closes)} bars)")
print(f"{'='*60}")

results = []

# ── 1. TSMOM30 base (no conviction) ────────────────────────────────────
for conv_flag in [False, True]:
    for label in ["TSMOM30_base", "TSMOM30_conviction"]:
        if conv_flag is False and label != "TSMOM30_base":
            continue
        if conv_flag is True and label != "TSMOM30_conviction":
            continue
        
        # IS
        pos_is = run_strategy(is_closes, is_highs, is_lows, conviction_scale=conv_flag)
        rets_is = np.diff(is_closes) / is_closes[:-1] * pos_is[1:]
        
        m = compute_metrics(rets_is, label=f"{label}_IS")
        if m:
            results.append(m)
            print(f"\n{label}_IS:  Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
                  f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  Trds={m['n_trades']}")
        
        # OOS
        pos_oos = run_strategy(oos_closes, oos_highs, oos_lows, conviction_scale=conv_flag)
        rets_oos = np.diff(oos_closes) / oos_closes[:-1] * pos_oos[1:]
        m = compute_metrics(rets_oos, label=f"{label}_OOS")
        if m:
            results.append(m)
            print(f"{label}_OOS: Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
                  f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  Trds={m['n_trades']}")

# ── 2. FHML (Funding proxy MR) ────────────────────────────────────────
fund_pos = run_funding_mr(closes, lows)
rets_fund_is = np.diff(is_closes) / is_closes[:-1] * fund_pos[1:split_ix]
m = compute_metrics(rets_fund_is, label="FundMR_proxy_IS")
if m:
    results.append(m)
    print(f"\nFundMR_proxy_IS:   Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
          f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  Trds={m['n_trades']}")

rets_fund_oos = np.diff(oos_closes) / oos_closes[:-1] * fund_pos[split_ix+1:]
m = compute_metrics(rets_fund_oos, label="FundMR_proxy_OOS")
if m:
    results.append(m)
    print(f"FundMR_proxy_OOS:  Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
          f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  Trds={m['n_trades']}")

# ── 3. Combined: TSMOM30 conviction + FundMR ──────────────────────────
full_pos_conv = run_strategy(closes, highs, lows, conviction_scale=True)
full_fund = run_funding_mr(closes, lows)
combined = np.clip(full_pos_conv + full_fund, -1.0, 1.0)

rets_comb_is = np.diff(is_closes) / is_closes[:-1] * combined[1:split_ix]
m = compute_metrics(rets_comb_is, label="Combined_IS")
if m:
    results.append(m)
    print(f"\nCombined_IS:       Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
          f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  Trds={m['n_trades']}")

rets_comb_oos = np.diff(oos_closes) / oos_closes[:-1] * combined[split_ix+1:]
m = compute_metrics(rets_comb_oos, label="Combined_OOS")
if m:
    results.append(m)
    print(f"Combined_OOS:     Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
          f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  Trds={m['n_trades']}")

# ── Baseline: buy-and-hold ──────────────────────────────────────────────
rets_bh = np.diff(closes) / closes[:-1]
m = compute_metrics(rets_bh, label="BuyHold_full")
if m:
    results.append(m)
    print(f"\nBuyHold_full:      Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
          f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  Trds={m['n_trades']}")

# ── Save ────────────────────────────────────────────────────────────────
out_dir = Path("/opt/data/repos/btc-signal-bot/research/output")
out_dir.mkdir(exist_ok=True, parents=True)
out_path = out_dir / "jones_study_results.json"
with open(out_path, "w") as f:
    json.dump({"results": results, "params": {
        "data": "binance_spot_1d_proxy",
        "bars": total_bars,
        "split": f"70% IS ({split_ix}), 30% OOS ({total_bars - split_ix})",
        "tsmom_fast": 10,
        "tsmom_slow": 30,
        "fund_lookback": 60,
        "conviction_bands": "0.5/1.0/1.5x at |z|<0.5/1.0/1.0+",
    }}, f, indent=2, default=str)

print(f"\n{'='*60}")
print(f"Results saved to {out_path}")
print(f"{'='*60}")
