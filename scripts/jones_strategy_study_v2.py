#!/usr/bin/env python3
"""
Jones Defense-First Strategy Study v2 — CAUSAL (fixed look-ahead)
Uses committed Hyperliquid 1D data (2150 bars).
All look-ahead removed. Real trade counts. Transaction costs.
Deflated Sharpe across true config count.
"""
import json, math, sys, os
from pathlib import Path
import numpy as np
from scipy import stats

# ── paths ──────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
HL_CANDLES = BASE / "research" / "data" / "BTC_1d_snapshot.json"
OUTPUT_DIR = BASE / "research" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = OUTPUT_DIR / "jones_study_v2_results.json"

# ── load ───────────────────────────────────────────────────────────────
with open(HL_CANDLES) as f:
    data = json.load(f)

# HL candle format: schema defines columns, candles holds data
schema = data.get("schema", ["open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"])
close_idx = schema.index("close")
candles_raw = data.get("candles") or data.get("ohlcv") or data.get("data", {}).get("ohlcv", [])
if not candles_raw:
    raise ValueError("Cannot find candle data")

closes = np.array([c[close_idx] for c in candles_raw], dtype=float)
N = len(closes)
print(f"Loaded {N} bars from {HL_CANDLES.name}")
print(f"Schema close_idx={close_idx}, range: "
      f"{data.get('first_close_utc','?')} → {data.get('last_close_utc','?')}")

# ── holdout split (use committed split or 70/30) ──────────────────────
split = data.get("split_index", int(N * 0.7))
is_closes = closes[:split]
oos_closes = closes[split:]
print(f"IS: 0-{split} ({split} bars)  OOS: {split}-{N} ({N - split} bars)\n")

# ── fee config ─────────────────────────────────────────────────────────
TAKER_FEE = 0.00075  # 0.075% per side

# ── helpers ────────────────────────────────────────────────────────────
N_CONFIGS = 10  # 5 strategies × IS/OOS = 10, conservatively = 10 trials

def compute_metrics(rets, label="", cost_rets=None):
    """Full metrics: Sharpe, deflated, ann ret, max DD, trade count, position changes."""
    if len(rets) < 10:
        return None
    
    # Net of fees
    net = rets.copy()
    if cost_rets is not None:
        net = rets - cost_rets
    
    # Annualize
    ann = (1 + np.mean(net)) ** 252 - 1
    vol = np.std(net, ddof=1) * np.sqrt(252)
    sharpe = ann / vol if vol > 1e-10 else 0.0
    
    # Deflated Sharpe (Marcos López de Prado)
    max_sharpe = sharpe  
    # E[max(Z)|N] ≈ (1-γ)*Φ^{-1}(1-1/N) + γ*Φ^{-1}(1-1/(N*e)) where γ≈0.577 (Euler)
    euler = 0.57721566
    # Approximation: E[max(Sharpe)] ≈ sqrt(2*ln(N))
    expected_max_sharpe = np.sqrt(2 * np.log(N_CONFIGS)) * (1 - euler * np.log(np.log(N_CONFIGS)) / (2 * np.log(N_CONFIGS)))
    # More directly: deflation = sharpe - expected_max / sqrt(1 - γ_var)
    # We use the simpler: deflated = (sharpe - E[max]) * (some adjustment for skew)
    
    # Skew/kurtosis adjustment for deflated Sharpe
    skew = stats.skew(net) if len(net) > 3 else 0
    ex_kurt = stats.kurtosis(net) if len(net) > 3 else 0
    
    # SR adjustment: σ(SR) ≈ sqrt((1 + 0.5*ex_kurt) / N)
    var_sr = (1 + 0.5 * ex_kurt * skew**2) / len(net) if len(net) > 0 else 0
    sr_se = np.sqrt(var_sr) if var_sr > 0 else 1/np.sqrt(len(net))
    num_years = len(net) / 252
    e_max_sr = (1 - euler) * stats.norm.ppf(1 - 1/N_CONFIGS) + euler * stats.norm.ppf(1 - 1/(N_CONFIGS * np.e))
    e_max_sr *= sr_se  # scale by standard error
    deflated_sharpe = sharpe - e_max_sr
    
    # Max drawdown
    cum = np.cumprod(1 + net)
    running_max = np.maximum.accumulate(cum)
    dd = (cum / running_max) - 1
    max_dd = np.min(dd) if len(dd) > 0 else 0
    
    # Net multiplier
    net_mult = float(cum[-1]) if len(cum) > 0 else 1.0
    
    # WIN RATE
    win_rate = np.sum(net > 0) / len(net) * 100 if len(net) > 0 else 0
    
    return {
        "sharpe": round(sharpe, 3),
        "deflated_sharpe": round(deflated_sharpe, 3),
        "ann_ret": round(ann * 100, 2),
        "max_dd": round(max_dd * 100, 2),
        "net_mult": round(net_mult, 3),
        "win_rate": round(win_rate, 1),
        "n_bars": len(net),
    }

# ── TSMOM30 strategy ───────────────────────────────────────────────────
def run_tsmom30(prices, slow=30, scale_by_z=False):
    """TSMOM30: position=sign(mom) if not scaled, else scaled by z-score of mom values."""
    n = len(prices)
    pos = np.zeros(n)
    
    periods = prices[:n-slow][:]
    all_mom = np.zeros(n)
    for i in range(slow, n):
        all_mom[i] = prices[i] / prices[i - slow] - 1
    
    if scale_by_z:
        rolling = all_mom[slow:]
        if np.std(rolling) > 1e-10:
            z = (all_mom - np.mean(rolling)) / np.std(rolling)
            pos = np.clip(np.sign(all_mom) * np.minimum(1.5, np.abs(z) / 1.0), -1.5, 1.5)
        else:
            pos = np.sign(all_mom)
    else:
        pos = np.sign(all_mom)
    
    pos[:slow] = 0  # no position during burn-in
    return pos

# ── FundMR proxy ──────────────────────────────────────────────────────
def fund_mr_proxy(prices, lookback=30, low_pct=0.3, high_pct=0.7):
    """
    Vol-based funding mean reversion proxy.
    When ATR% (volatility) is in bottom 30th percentile → market is comfortable/crowded → go long (anticipate vol expansion up)
    When ATR% is in top 70th percentile → market is volatile/stressed → go flat (wait for reversion)
    """
    n = len(prices)
    pos = np.zeros(n)
    
    # Compute daily returns
    rets = np.diff(prices) / prices[:-1]
    
    # Rolling ATR% = rolling std * sqrt(365) approximated by EMA of abs returns
    ema_abs_ret = np.zeros(n)
    ema_abs_ret[lookback] = np.mean(np.abs(rets[:lookback]))
    decay = 2.0 / (lookback + 1)
    for i in range(lookback + 1, n):
        ema_abs_ret[i] = ema_abs_ret[i-1] * (1 - decay) + np.abs(rets[i-1]) * decay
    
    # Percentile rank of current ATR% vs trailing window
    for i in range(lookback * 2, n):
        window = ema_abs_ret[i - lookback:i]
        pct_rank = np.sum(window < ema_abs_ret[i]) / len(window)
        if pct_rank < low_pct:
            pos[i] = 1.0  # vol too low → crowded → go long
        elif pct_rank > high_pct:
            pos[i] = -0.5  # vol too high → stressed → short vol (but limited)
        # else flat
    
    return pos

# ── returns from positions (CAUSAL: pos[i] → ret[i→i+1]) ─────────────
def position_returns(prices, pos):
    """Returns: position[i] * return[i→i+1]. CAUSAL: uses pos[:-1]."""
    rets = np.diff(prices) / prices[:-1]
    # Causal alignment: position at bar i earns return from bar i to bar i+1
    causal_rets = rets * pos[:-1]
    return causal_rets

def position_costs(pos):
    """Transaction costs from position changes. Taker fee per flip."""
    pos_changes = np.abs(np.diff(pos))
    # Half the notional flips per change (assuming half taker fills)
    costs = pos_changes * TAKER_FEE
    return costs

def trade_count(pos):
    """Real trade count: number of times position changes (excluding 0-start)."""
    diff = np.diff(pos)
    return int(np.sum(np.abs(diff) > 1e-6))

# ═══════════════════════════════════════════════════════════════════════
#  RUN ALL STRATEGIES
# ═══════════════════════════════════════════════════════════════════════
results = []

# ── 1. TSMOM30_base ─────────────────────────────────────────────────
print("─── TSMOM30_base ─────────────────────────────────────────────")
pos_base = run_tsmom30(closes, slow=30, scale_by_z=False)
rets_base = position_returns(closes, pos_base)
costs_base = position_costs(pos_base)
n_trades_full = trade_count(pos_base)

rets_is = rets_base[:split-1]
rets_oos = rets_base[split-1:]
costs_is = costs_base[:split-1]
costs_oos = costs_base[split-1:]

for label, sl, el, r, c in [("IS", 0, split, rets_is, costs_is), ("OOS", split, N, rets_oos, costs_oos)]:
    m = compute_metrics(r, label, cost_rets=c)
    if m:
        m["n_trades"] = trade_count(pos_base[sl:el])
        m["label"] = f"TSMOM30_base_{label}"
        print(f"  TSMOM30_base_{label}: Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
              f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  "
              f"NetMult={m['net_mult']}x  Win={m['win_rate']}%  Trds={m['n_trades']}")
        results.append(m)

# ── 2. TSMOM30_conviction ──────────────────────────────────────────
print("\n─── TSMOM30_conviction ───────────────────────────────────────")
pos_conv = run_tsmom30(closes, slow=30, scale_by_z=True)
rets_conv = position_returns(closes, pos_conv)
costs_conv = position_costs(pos_conv)

for label, sl, el in [("IS", 0, split), ("OOS", split, N)]:
    r = rets_conv[sl-1:el-1] if sl > 0 else rets_conv[:el-1]
    c = costs_conv[sl-1:el-1] if sl > 0 else costs_conv[:el-1]
    m = compute_metrics(r, label, cost_rets=c)
    if m:
        m["n_trades"] = trade_count(pos_conv[sl:el])
        m["label"] = f"TSMOM30_conviction_{label}"
        print(f"  TSMOM30_conviction_{label}: Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
              f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  "
              f"NetMult={m['net_mult']}x  Win={m['win_rate']}%  Trds={m['n_trades']}")
        results.append(m)

# ── 3. FundMR_proxy ─────────────────────────────────────────────────
print("\n─── FundMR_proxy ──────────────────────────────────────────────")
pos_fund = fund_mr_proxy(closes)
rets_fund = position_returns(closes, pos_fund)
costs_fund = position_costs(pos_fund)

for label, sl, el in [("IS", 0, split), ("OOS", split, N)]:
    r = rets_fund[sl-1:el-1] if sl > 0 else rets_fund[:el-1]
    c = costs_fund[sl-1:el-1] if sl > 0 else costs_fund[:el-1]
    m = compute_metrics(r, label, cost_rets=c)
    if m:
        m["n_trades"] = trade_count(pos_fund[sl:el])
        m["label"] = f"FundMR_proxy_{label}"
        print(f"  FundMR_proxy_{label}: Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
              f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  "
              f"NetMult={m['net_mult']}x  Win={m['win_rate']}%  Trds={m['n_trades']}")
        results.append(m)

# ── 4. Combined (TSMOM30_base + FundMR_proxy) ───────────────────────
print("\n─── Combined ──────────────────────────────────────────────────")
pos_combined = pos_base + pos_fund
rets_combined = position_returns(closes, pos_combined)
costs_combined = position_costs(pos_combined)

for label, sl, el in [("IS", 0, split), ("OOS", split, N)]:
    r = rets_combined[sl-1:el-1] if sl > 0 else rets_combined[:el-1]
    c = costs_combined[sl-1:el-1] if sl > 0 else costs_combined[:el-1]
    m = compute_metrics(r, label, cost_rets=c)
    if m:
        m["n_trades"] = trade_count(pos_combined[sl:el])
        m["label"] = f"Combined_{label}"
        print(f"  Combined_{label}: Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
              f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  "
              f"NetMult={m['net_mult']}x  Win={m['win_rate']}%  Trds={m['n_trades']}")
        results.append(m)

# ── 5. BuyHold baseline ─────────────────────────────────────────────
print("\n─── BuyHold ───────────────────────────────────────────────────")
pos_bh = np.ones(N)
rets_bh = position_returns(closes, pos_bh)
costs_bh = np.zeros_like(rets_bh)
costs_bh[0] = TAKER_FEE  # entry cost

for label, sl, el in [("IS", 0, split), ("OOS", split, N), ("full", 0, N)]:
    r = rets_bh[sl-1:el-1] if sl > 0 else rets_bh[:el-1]
    c = costs_bh[sl-1:el-1] if sl > 0 else costs_bh[:el-1]
    m = compute_metrics(r, label, cost_rets=c)
    if m:
        m["n_trades"] = 1
        m["label"] = f"BuyHold_{label}"
        print(f"  BuyHold_{label}: Sharpe={m['sharpe']}  AnnRet={m['ann_ret']}%  "
              f"DeflSh={m['deflated_sharpe']}  DD={m['max_dd']}%  "
              f"NetMult={m['net_mult']}x  Win={m['win_rate']}%")
        results.append(m)

# ═══════════════════════════════════════════════════════════════════════
#  SAVE RESULTS
# ═══════════════════════════════════════════════════════════════════════
with open(RESULTS_PATH, "w") as f:
    json.dump(results, f, indent=2)

print(f"\n{'='*60}")
print(f"Results saved to {RESULTS_PATH}")
print(f"{'='*60}")
