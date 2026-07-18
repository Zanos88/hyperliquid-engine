"""Explore raw funding data for custom threshold strategies."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from datetime import datetime, timezone
from bisect import bisect_left, bisect_right

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import OUTPUT_DIR, load_snapshot
from strategy_tournament import BARS_PER_YEAR, FEE, WARMUP, log_returns, metrics, net_strategy_returns

DAY_MS = 86_400_000
FUNDING_PATH = SCRIPTS_DIR.parent / "research" / "data" / "BTC_funding_history.json"

candles, _ = load_snapshot("1d")
rets = log_returns(candles)
bpy = BARS_PER_YEAR["1d"]
closes = [c.close for c in candles]

# Load raw funding data
print(f"Loading funding from {FUNDING_PATH}...")
fund_doc = json.loads(FUNDING_PATH.read_text())
fund_rows = fund_doc["rows"]
print(f"Raw funding rows: {len(fund_rows)}")

# Compute 30d avg funding aligned to daily bars
MDAYS = 30
MS30 = MDAYS * DAY_MS
ftimes = [int(t) for t, _ in fund_rows]
fvals = [float(v) for _, v in fund_rows]

fund_avg = [None] * len(candles)
for i, c in enumerate(candles):
    ce = c.close_time_ms
    lo = bisect_left(ftimes, ce - MS30)
    hi = bisect_right(ftimes, ce)
    win = fvals[lo:hi]
    if win:
        fund_avg[i] = sum(win) / len(win)

# Compute running percentile within trailing 365d
W365 = 365 * DAY_MS
fund_pctile = [None] * len(candles)
for i in range(len(candles)):
    if fund_avg[i] is None:
        continue
    ce = candles[i].close_time_ms
    lo_ms = ce - W365
    window = [fund_avg[j] for j in range(i + 1)
              if fund_avg[j] is not None and candles[j].close_time_ms >= lo_ms]
    if len(window) < 100:
        continue
    cur = fund_avg[i]
    pct = 100.0 * sum(1 for v in window if v <= cur) / len(window)
    fund_pctile[i] = pct

vals = [p for p in fund_pctile if p is not None]
print(f"\nFunding percentile bars: {len(vals)}/{len(candles)}")
print(f"  Min: {min(vals):.1f}%  Max: {max(vals):.1f}%  Mean: {sum(vals)/len(vals):.1f}%")

ee = len(candles) - 1
a = max(WARMUP, 365)

# Custom LONG thresholds
print("\n=== LONG (funding below threshold) ===")
for name, threshold in [
    ("pct<=5", 5.0), ("pct<=10", 10.0), ("pct<=15", 15.0),
    ("pct<=20", 20.0), ("pct<=25", 25.0), ("pct<=30 (BEAR)", 30.0),
    ("pct<=35", 35.0), ("pct<=40", 40.0), ("pct<=50", 50.0),
]:
    pos = [1 if i < len(candles) and fund_pctile[i] is not None and fund_pctile[i] <= threshold else 0
           for i in range(len(candles))]
    if sum(pos) == 0:
        print(f"  {name:20s}: NO SIGNALS"); continue
    net = net_strategy_returns(pos, rets)
    m = metrics(net, pos, a, ee, bpy)
    print(f"  {name:20s}: Sh={m['sharpe']:.3f}  Ret={m['ann_return_pct']:7.2f}%  "
          f"DD={m['max_dd_log']:.4f}  Trades={m['trades']:3.0f}  "
          f"Exp={m['exposure']*100:.0f}%  Net={m['net_multiple']:.4f}")

# SHORT side
print("\n=== SHORT (funding above threshold, using flipped returns) ===")
rets_flipped = [-r for r in rets]
for name, threshold in [
    ("pct>=60", 60.0), ("pct>=70", 70.0), ("pct>=75", 75.0),
    ("pct>=80", 80.0), ("pct>=85", 85.0), ("pct>=90", 90.0), ("pct>=95", 95.0),
]:
    pos = [1 if i < len(candles) and fund_pctile[i] is not None and fund_pctile[i] >= threshold else 0
           for i in range(len(candles))]
    if sum(pos) == 0:
        print(f"  {name:20s}: NO SIGNALS"); continue
    net = net_strategy_returns(pos, rets_flipped)
    m = metrics(net, pos, a, ee, bpy)
    print(f"  {name:20s}: Sh={m['sharpe']:.3f}  Ret={m['ann_return_pct']:7.2f}%  "
          f"DD={m['max_dd_log']:.4f}  Trades={m['trades']:3.0f}  "
          f"Exp={m['exposure']*100:.0f}%  Net={m['net_multiple']:.4f}")

# COMBINED long+short
print("\n=== COMBINED (funding extremes, both sides) ===")
for long_pct, short_pct in [(10, 90), (15, 85), (20, 80), (25, 75), (30, 65)]:
    long_pos = [1 if fund_pctile[i] is not None and fund_pctile[i] <= long_pct else 0
                for i in range(len(candles))]
    short_pos = [1 if fund_pctile[i] is not None and fund_pctile[i] >= short_pct else 0
                 for i in range(len(candles))]
    net_long = net_strategy_returns(long_pos, rets)
    net_short = net_strategy_returns(short_pos, rets_flipped)
    combined_net = [nl + ns for nl, ns in zip(net_long, net_short)]
    comb_pos = [1 if lp or sp else 0 for lp, sp in zip(long_pos, short_pos)]
    m = metrics(combined_net, comb_pos, a, ee, bpy)
    print(f"  L<={long_pct:2d}/S>={short_pct:2d}%: Sh={m['sharpe']:.3f}  "
          f"Ret={m['ann_return_pct']:7.2f}%  DD={m['max_dd_log']:.4f}  "
          f"Trades={m['trades']:3.0f}  Exp={m['exposure']*100:.0f}%  Net={m['net_multiple']:.4f}")

# HOLDING PERIOD on pct<=30
print("\n=== HOLDING PERIOD (enter pct<=30, exit after N bars) ===")
for hold_bars in [7, 14, 21, 30, 45, 60]:
    pos = [0] * len(candles)
    timer = 0
    for i in range(len(candles)):
        if timer == 0 and fund_pctile[i] is not None and fund_pctile[i] <= 30.0:
            timer = hold_bars
        if timer > 0:
            pos[i] = 1
            timer -= 1
    if sum(pos) == 0: continue
    net = net_strategy_returns(pos, rets)
    m = metrics(net, pos, a, ee, bpy)
    print(f"  Hold {hold_bars:2d}d: Sh={m['sharpe']:.3f}  Ret={m['ann_return_pct']:7.2f}%  "
          f"DD={m['max_dd_log']:.4f}  Trades={m['trades']:3.0f}  "
          f"Exp={m['exposure']*100:.0f}%  Net={m['net_multiple']:.4f}")
