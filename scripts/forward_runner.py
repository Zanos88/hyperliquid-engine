#!/usr/bin/env python3
"""
Forward-runner: TSMOM30 + FundMR proxy signal generator.
Reads live candle data from mirror + candles-binance, computes positions,
outputs a formatted signal for cron delivery.

Usage:
  python3 scripts/forward_runner.py              # full output
  python3 scripts/forward_runner.py --compact     # one-line summary
"""
from __future__ import annotations
import json, sys, os
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

# ── paths ──────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
CANDLES_PATH = Path("/opt/data/candles-binance/BTC_1d_snapshot.json")
MIRROR_PATH = Path("/opt/data/mirror/market_state.json")
SIGNAL_LOG = BASE / "research" / "output" / "forward_signal_history.json"
STRATEGY_LOG = BASE / "research" / "output" / "forward_runner_state.json"

# ── helpers ─────────────────────────────────────────────────────────────
def load_candles():
    """Load Binance proxy candles. Returns (prices, utc_dates)."""
    with open(CANDLES_PATH) as f:
        data = json.load(f)
    
    schema = data.get("schema", [])
    close_idx = schema.index("close") if "close" in schema else 5
    candles = data.get("candles", [])
    
    closes = np.array([c[close_idx] for c in candles], dtype=float)
    # Extract dates from candle schema: open_time_ms is index 0
    open_time_idx = 0
    dates = []
    for c in candles:
        ts_ms = c[open_time_idx]
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        dates.append(dt.strftime("%Y-%m-%d"))
    
    print(f"  Loaded {len(closes)} daily candles")
    print(f"  Range: {dates[0]} → {dates[-1]}")
    print(f"  Latest close: ${closes[-1]:,.2f} on {dates[-1]}")
    return closes, dates

def get_latest_price():
    """Get latest BTC price from mirror."""
    if not MIRROR_PATH.exists():
        print("  ⚠ mirror/market_state.json not found")
        return None
    
    with open(MIRROR_PATH) as f:
        data = json.load(f)
    
    if isinstance(data, list) and len(data) > 0:
        item = data[0]
        price = item.get("last_price")
        ts = item.get("ts", "?")
        if price:
            print(f"  Mirror: BTC ${price:,.2f} at {ts[:19]}")
            return price
    return None

def build_price_series(historical, latest):
    """Append latest price to historical series."""
    if latest is not None:
        extended = np.append(historical, latest)
        print(f"  Extended to {len(extended)} bars (latest ${latest:,.2f})")
        return extended
    return historical

# ── strategy logic ─────────────────────────────────────────────────────
def tsmom30(prices, slow=30):
    """TSMOM30: sign(momentum), position is +1 or -1. Returns pos array."""
    n = len(prices)
    pos = np.zeros(n)
    for i in range(slow, n):
        mom = prices[i] / prices[i - slow] - 1
        pos[i] = 1.0 if mom > 0 else -1.0
    return pos

def tsmom30_conviction(prices, slow=30):
    """TSMOM30 with conviction pyramid scaling. Positions from 0.5x to 1.5x."""
    n = len(prices)
    pos = np.zeros(n)
    # Pre-compute all momentum values
    mom_vals = np.zeros(n)
    for i in range(slow, n):
        mom_vals[i] = prices[i] / prices[i - slow] - 1
    
    valid = mom_vals[slow:]
    if np.std(valid) > 1e-10:
        mean_mom = np.mean(valid)
        std_mom = np.std(valid)
        z = (mom_vals - mean_mom) / std_mom
        # Scale: 0.5x at z=0, 1.5x at |z|=2, capped at 1.5x
        scale = np.minimum(1.5, 0.5 + np.abs(z) * 0.5)
        pos = np.sign(mom_vals) * np.where(scale > 0.25, scale, 0.25)
        pos[:slow] = 0
    else:
        pos[:slow] = 0
        pos[slow:] = np.sign(mom_vals[slow:])
    return pos

def fund_mr_proxy(prices, lookback=30, low_pct=0.3, high_pct=0.7):
    """
    Vol-based funding MR proxy.
    Low vol (bottom 30%) → crowded → go long
    High vol (top 70%) → distressed → short vol (limited)
    """
    n = len(prices)
    pos = np.zeros(n)
    rets = np.diff(prices) / prices[:-1]
    
    # EMA of absolute returns as ATR% proxy
    ema = np.zeros(n)
    ema[lookback] = np.mean(np.abs(rets[:lookback]))
    decay = 2.0 / (lookback + 1)
    for i in range(lookback + 1, n):
        ema[i] = ema[i-1] * (1 - decay) + np.abs(rets[i-1]) * decay
    
    for i in range(lookback * 2, n):
        window = ema[i - lookback:i]
        pct = np.sum(window < ema[i]) / len(window)
        if pct < low_pct:
            pos[i] = 1.0   # vol compression → go long
        elif pct > high_pct:
            pos[i] = -0.5  # vol expansion → short vol
    
    return pos

# ── main ───────────────────────────────────────────────────────────────
def main(compact=False):
    print("═══ Forward Runner ═══")
    print(f"  UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Load data
    print("── Data ──")
    closes, dates = load_candles()
    latest = get_latest_price()
    prices = build_price_series(closes, latest)
    print()
    
    # Compute signals
    print("── Signals ──")
    pos_base = tsmom30(prices)
    pos_conv = tsmom30_conviction(prices)
    pos_fund = fund_mr_proxy(prices)
    pos_combined = pos_base + pos_fund
    # Cap combined
    pos_combined = np.clip(pos_combined, -1.5, 1.5)
    
    # Current position (last bar)
    idx = -1
    sig_base = pos_base[idx]
    sig_conv = pos_conv[idx]
    sig_fund = pos_fund[idx]
    sig_combined = pos_combined[idx]
    price = prices[idx]
    
    def direction(v):
        if v > 0.5: return "BULL"
        if v > 0.1: return "LONG"
        if v < -0.5: return "BEAR"
        if v < -0.1: return "SHORT"
        return "FLAT"
    
    print(f"  │ {'Strategy':<25} {'Signal':<8} {'Size':<6} │")
    print(f"  ├{'─'*42}┤")
    print(f"  │ {'TSMOM30_base':<25} {direction(sig_base):<8} {sig_base:<6.2f} │")
    print(f"  │ {'TSMOM30_conviction':<25} {direction(sig_conv):<8} {sig_conv:<6.2f} │")
    print(f"  │ {'FundMR_proxy':<25} {direction(sig_fund):<8} {sig_fund:<6.2f} │")
    print(f"  │ {'Combined':<25} {direction(sig_combined):<8} {sig_combined:<6.2f} │")
    print(f"  └{'─'*42}┘")
    print(f"  BTC price: ${price:,.2f}")
    print()
    
    # Model-level reasoning
    print("── Reasoning ──")
    # TSMOM30
    mom_30 = prices[-1] / prices[-31] - 1 if len(prices) >= 31 else 0
    print(f"  TSMOM30: 30d momentum = {mom_30*100:+.2f}% → {direction(sig_base)}")
    
    # FundMR
    ret_5d = prices[-1] / prices[-6] - 1 if len(prices) >= 6 else 0
    ret_20d = prices[-1] / prices[-21] - 1 if len(prices) >= 21 else 0
    print(f"  Price: 5d={ret_5d*100:+.2f}%  20d={ret_20d*100:+.2f}%")
    
    # Vol proxy
    # Vol proxy — use min(60, available) bars of returns
    n_vol = min(60, len(prices) - 1)
    # Need +1 extra price to compute n_vol returns
    window_prices = prices[-(n_vol+1):]
    vol_rets = np.diff(window_prices) / window_prices[:-1]
    recent_vol = np.std(vol_rets[-5:]) * np.sqrt(365) if len(vol_rets) >= 5 else 0
    hist_vol = np.std(vol_rets) * np.sqrt(365) if len(vol_rets) > 30 else 0
    print(f"  Vol (ann): recent={recent_vol*100:.1f}%  hist={hist_vol*100:.1f}%")
    
    if sig_base > 0 and sig_fund > 0:
        print(f"  ⚡ CONFLUENCE: TSMOM30 bullish + fundMR cheap → {direction(sig_combined)} {np.abs(sig_combined):.2f}x")
    elif sig_base > 0 and sig_fund < 0:
        print(f"  → Mixed: trend {'up' if sig_base > 0 else 'down'}, vol {'compressed' if sig_fund > 0 else 'stressed'}")
    else:
        print(f"  → {direction(sig_combined)} with conviction {np.abs(sig_combined):.2f}x")
    
    # Save state
    state = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "btc_price": round(price, 2),
        "signals": {
            "tsmom30_base": {"direction": direction(sig_base), "size": round(sig_base, 3)},
            "tsmom30_conviction": {"direction": direction(sig_conv), "size": round(sig_conv, 3)},
            "fund_mr_proxy": {"direction": direction(sig_fund), "size": round(sig_fund, 3)},
            "combined": {"direction": direction(sig_combined), "size": round(sig_combined, 3)},
        },
        "metrics": {
            "mom_30d_pct": round(mom_30 * 100, 2),
            "ret_5d_pct": round(ret_5d * 100, 2),
            "ret_20d_pct": round(ret_20d * 100, 2),
            "vol_recent_ann_pct": round(recent_vol * 100, 1),
            "vol_hist_ann_pct": round(hist_vol * 100, 1),
        }
    }
    STRATEGY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(STRATEGY_LOG, "w") as f:
        json.dump(state, f, indent=2)
    
    # Append to signal history (keep last 100)
    try:
        with open(SIGNAL_LOG) as f:
            history = json.load(f)
        if not isinstance(history, list):
            history = []
    except (FileNotFoundError, json.JSONDecodeError):
        history = []
    
    history.append({
        "ts": state["ts"],
        "price": state["btc_price"],
        "combined_dir": direction(sig_combined),
        "combined_size": round(sig_combined, 3),
        "mom_30d": round(mom_30 * 100, 2),
    })
    if len(history) > 100:
        history = history[-100:]
    
    with open(SIGNAL_LOG, "w") as f:
        json.dump(history, f, indent=2)
    
    print(f"\n── Saved ──")
    print(f"  State → {STRATEGY_LOG}")
    print(f"  History → {SIGNAL_LOG} ({len(history)} entries)")
    
    if compact:
        # One-line summary for cron delivery
        combined_dir = direction(sig_combined)
        combined_size = np.abs(sig_combined)
        dir_emoji = "🟢" if combined_dir in ("BULL","LONG") else ("🔴" if combined_dir in ("BEAR","SHORT") else "⚪")
        print(f"\n═══ ONE-LINE ═══")
        print(f"{dir_emoji} BTC ${price:,.0f} | Combined {combined_dir} {combined_size:.2f}x | "
              f"TSMOM {direction(sig_base)} | FundMR {direction(sig_fund)} | "
              f"30dMom {mom_30*100:+.1f}%")
    
    return 0

if __name__ == "__main__":
    compact = "--compact" in sys.argv
    sys.exit(main(compact=compact))
