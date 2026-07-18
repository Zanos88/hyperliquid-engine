"""Deep-dive on funding MR — Sharpe 1.003 is the best result so far.
Check signal density, trace actual trades, test variants."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from datetime import datetime, timezone

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import OUTPUT_DIR, load_snapshot
from strategy_tournament import BARS_PER_YEAR, FEE, WARMUP, log_returns, metrics, net_strategy_returns, eval_bounds, sma_positions

def load_regime_labels():
    path = OUTPUT_DIR / "regime_labels_btc.json"
    doc = json.loads(path.read_text())
    return {r["close_ms"]: r for r in doc["labels"]}

def ms2s(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

def _sma(lst, w):
    out, s = [], 0.0
    for i, v in enumerate(lst):
        s += v
        if i >= w: s -= lst[i - w]
        out.append(s / w if i >= w - 1 else 0.0)
    return out

candles, _ = load_snapshot("1d")
rets = log_returns(candles)
bpy = BARS_PER_YEAR["1d"]
a, ee, _ = eval_bounds(len(candles))

regime_info = load_regime_labels()
closes = [c.close for c in candles]

# 1. Funding regime frequencies
fund_freq = {"BULL": 0, "BEAR": 0, "NEUTRAL": 0, None: 0}
bear_bars = []
for i, c in enumerate(candles):
    r = regime_info.get(c.close_time_ms, {})
    f = r.get("funding")
    fund_freq[f] = fund_freq.get(f, 0) + 1
    if f == "BEAR": bear_bars.append(i)

print(f"Funding regime frequencies: {fund_freq}")
print(f"BEAR bars (cheap shorts → go long): {len(bear_bars)}")

# 2. Trace funding MR trades
sma50 = _sma(closes, 50)

pos_fmr = [0] * len(candles)
for i in range(365, len(candles)):
    r = regime_info.get(candles[i].close_time_ms, {})
    f = r.get("funding")
    if f == "BEAR": pos_fmr[i] = 1
    elif f == "BULL": pos_fmr[i] = 0

print("\n=== Funding MR Trade Trace ===")
trade = False
entry_i = entry_px = 0
for i in range(len(candles)):
    if not trade and pos_fmr[i]:
        trade, entry_i, entry_px = True, i, candles[i].close
    elif trade and not pos_fmr[i]:
        exit_px = candles[i].close
        net_log = math.log(exit_px / entry_px) - FEE * 2
        net_pct = (exit_px / entry_px - 1) * 100
        bars = i - entry_i
        print(f"  [{ms2s(candles[entry_i].close_time_ms)} → {ms2s(candles[i].close_time_ms)}] "
              f"{bars:3d}d, entry=${entry_px:.0f}, exit=${exit_px:.0f}, net={net_pct:+.2f}%, log_ret={net_log:+.4f}")
        trade = False

# 3. Funding MR + SMA50 uptrend filter
pos_hyb = [0] * len(candles)
for i in range(365, len(candles)):
    r = regime_info.get(candles[i].close_time_ms, {})
    f = r.get("funding")
    trend_up = i >= 50 and closes[i] > sma50[i]
    if f == "BEAR" and trend_up: pos_hyb[i] = 1

net_h = net_strategy_returns(pos_hyb, rets)
m_h = metrics(net_h, pos_hyb, a, ee, bpy)
print(f"\n=== Funding MR + SMA50 Trend Filter ===")
print(f"  Sharpe={m_h['sharpe']:.4f}  Ret={m_h['ann_return_pct']:.2f}%  DD={m_h['max_dd_log']:.4f}  "
      f"Trades={m_h['trades']:.0f}  Exp={m_h['exposure']*100:.1f}%  Net={m_h['net_multiple']:.4f}")

# 4. Funding MR + TSMOM90 (longer trend)
pos_ts90 = [0] * len(candles)
for i in range(365, len(candles)):
    r = regime_info.get(candles[i].close_time_ms, {})
    f = r.get("funding")
    trend_up = i >= 90 and closes[i] > closes[i - 90]
    if f == "BEAR" and trend_up: pos_ts90[i] = 1

net_90 = net_strategy_returns(pos_ts90, rets)
m_90 = metrics(net_90, pos_ts90, a, ee, bpy)
print(f"\n=== Funding MR + TSMOM90 Trend Filter ===")
print(f"  Sharpe={m_90['sharpe']:.4f}  Ret={m_90['ann_return_pct']:.2f}%  DD={m_90['max_dd_log']:.4f}  "
      f"Trades={m_90['trades']:.0f}  Exp={m_90['exposure']*100:.1f}%  Net={m_90['net_multiple']:.4f}")

# 5. Funding MR with partial trim at BULL (scale IN to 75% at BEAR, exit remaining at BULL)
# BEAR=long 75% size, NEUTRAL=flat, BULL=flat
pos_pct = [0.0] * len(candles)
for i in range(365, len(candles)):
    r = regime_info.get(candles[i].close_time_ms, {})
    f = r.get("funding")
    if f == "BEAR": pos_pct[i] = 0.75

net_pct = net_strategy_returns(pos_pct, rets)  # uses float positions — won't work with fee calc on abs diff
m_pct = metrics(net_pct, [int(p > 0) for p in pos_pct], a, ee, bpy)
print(f"\n=== Funding MR 75% (BEAR=75%) ===")
print(f"  Sharpe={m_pct['sharpe']:.4f}  Ret={m_pct['ann_return_pct']:.2f}%  DD={m_pct['max_dd_log']:.4f}  "
      f"Trades={m_pct['trades']:.0f}  Exp={m_pct['exposure']*100:.1f}%  Net={m_pct['net_multiple']:.4f}")

# 6. FUNDING THRESHOLD VARIANT: long when funding in bottom 10th percentile (more extreme)
# funding BULL = pct >= 70, BEAR = pct <= 30. Let's try bottom 15%.
# Actually the labels only give us BEAR (≤30th) — let's try different: make our own funding percentile
# using the raw funding data instead of the labels
# For now, compare with regime_split to see if funding signal quality changes with more extreme thresholds

# 7. FUNDING + TSMOM30 COMBO (both signals must agree)
pos_combined = [0] * len(candles)
for i in range(max(365, 30), len(candles)):
    r = regime_info.get(candles[i].close_time_ms, {})
    f = r.get("funding")
    ts_up = closes[i] > closes[i - 30]
    if f == "BEAR" and ts_up: pos_combined[i] = 1

net_comb = net_strategy_returns(pos_combined, rets)
m_comb = metrics(net_comb, pos_combined, a, ee, bpy)
print(f"\n=== Funding BEAR + TSMOM30 uptrend ===")
print(f"  Sharpe={m_comb['sharpe']:.4f}  Ret={m_comb['ann_return_pct']:.2f}%  DD={m_comb['max_dd_log']:.4f}  "
      f"Trades={m_comb['trades']:.0f}  Exp={m_comb['exposure']*100:.1f}%  Net={m_comb['net_multiple']:.4f}")

# 8. SUMMARIZE
print("\n=============== COMPARISON ===============")
for name, m in [
    ("Funding MR standalone", metrics(net_strategy_returns(pos_fmr, rets), pos_fmr, a, ee, bpy)),
    ("Funding MR + SMA50", m_h),
    ("Funding MR + TSMOM90", m_90),
    ("Funding MR + TSMOM30", m_comb),
    ("Funding MR 75% size", m_pct),
    ("TSMOM30 baseline", metrics(net_strategy_returns(
        [1 if i >= 30 and closes[i] > closes[i-30] else 0 for i in range(len(candles))], rets),
        [1 if i >= 30 and closes[i] > closes[i-30] else 0 for i in range(len(candles))], a, ee, bpy)),
]:
    print(f"  {name:30s} Sh={m['sharpe']:.3f}  Ret={m['ann_return_pct']:7.2f}%  DD={m['max_dd_log']:.4f}  "
          f"Trades={m['trades']:3.0f}  Exp={m['exposure']*100:.0f}%  Net={m['net_multiple']:.4f}")
