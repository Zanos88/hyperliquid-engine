"""Breakout-Continuation — key-level break + volume, 15m/1H trigger on 4H trend.

A third archetype (distinct from trend-confluence and Track 4 mean-reversion):
CHASES a break of a prior swing level in the higher-timeframe trend direction,
confirmed by real volume, with a structurally tight stop just beyond the broken
level. Entry fires ON the breakout bar's close (aggressive chase, not a retest).
BACKTEST ONLY; SIMULATED (idealized stop/target fills — no slippage/gap; 15m
breakouts would fill worse live). Reuses detect_swings, wilder_atr, compute_bias,
sma — no duplicated level/ATR/bias logic.

Sweep: bias {sma, fibsr} x TF {15m, 1h} x target {2r, structural} x
vol_mult {1.5, 2, 3} = 24 cells. Liquidity floor fixed per TF (measured 20th
pctile). No-lookahead: swings (fractals never repaint once formed), volume
average, and 4H bias all use only data <= the trigger bar close.

Usage: python scripts/breakout_continuation.py --phase {selfcheck,run}
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import OUTPUT_DIR  # noqa: E402 (adds repo root to path)
from data.feed import Candle, fetch_candles  # noqa: E402
from strategy.atr import wilder_atr  # noqa: E402
from strategy.bias_4h import Bias, SwingDirection, compute_bias, detect_swings  # noqa: E402
from strategy.timeframes import interval_seconds  # noqa: E402
from strategy.trigger_1h import sma  # noqa: E402

TRIGGER_TFS = ("15m", "1h")
BIAS_METHODS = ("sma", "fibsr")
TARGETS = ("2r", "structural")
VOL_MULTS = (1.5, 2.0, 3.0)
FEE = 0.00075
FRACTAL_WIDTH = 2
ATR_PERIOD = 14
VOL_AVG_WINDOW = 20
STOP_BUFFER_ATR = 0.25
SMA_WINDOW = 50
BIAS_LOOKBACK_4H = 300
FLOOR_PCTILE = 0.20
WARMUP = 60
MIN_RR = 2.0
OUT = OUTPUT_DIR / "breakout_continuation.json"


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def volume_floor(candles: list[Candle]) -> float:
    v = sorted(c.volume for c in candles)
    return v[int(FLOOR_PCTILE * len(v))]


def bias_series_4h(candles_4h: list[Candle], method: str) -> tuple[list[int], list[int]]:
    """Per-4H-bar bias sign (+1/-1/0), causal. Returns (signs, close_ms)."""
    closes = [c.close for c in candles_4h]
    signs = [0] * len(candles_4h)
    if method == "sma":
        s = sma(closes, SMA_WINDOW)
        for i in range(len(candles_4h)):
            if i >= SMA_WINDOW - 1:
                signs[i] = 1 if closes[i] > s[i] else (-1 if closes[i] < s[i] else 0)
    else:  # fibsr — compute_bias on the trailing lookback slice per bar
        for i in range(len(candles_4h)):
            if i < 30:
                continue
            window = candles_4h[max(0, i - BIAS_LOOKBACK_4H + 1): i + 1]
            b = compute_bias(window).bias
            signs[i] = 1 if b == Bias.BULLISH else (-1 if b == Bias.BEARISH else 0)
    return signs, [c.close_time_ms for c in candles_4h]


def confirmed_levels(candles: list[Candle]):
    """Full-series swing highs/lows with the bar index at which each becomes
    CONFIRMED (end_index + fractal_width). Fractals never repaint once formed
    (bias_4h.detect_swings docstring), so filtering these by confirmed<=i is
    identical to recomputing detect_swings(candles[:i+1]) — but O(n) not O(n^2)."""
    swings = detect_swings(candles, FRACTAL_WIDTH)
    highs, lows = [], []
    for s in swings:
        confirmed_at = s.end_index + FRACTAL_WIDTH
        if s.direction == SwingDirection.UP:
            highs.append((confirmed_at, s.end_price))
        else:
            lows.append((confirmed_at, s.end_price))
    highs.sort(); lows.sort()
    return highs, lows


def run_cell(trig: list[Candle], tf: str, bias_signs, bias_ms, target: str,
             vol_mult: float, floor: float) -> list[dict]:
    n = len(trig)
    atr = wilder_atr(trig, ATR_PERIOD)
    vols = [c.volume for c in trig]
    vol_avg = sma(vols, VOL_AVG_WINDOW)
    highs, lows = confirmed_levels(trig)
    hi_cur = lo_cur = 0
    last_high = last_low = None
    all_high_prices: list[float] = []   # confirmed swing-high prices so far (for structural target)
    all_low_prices: list[float] = []
    trades: list[dict] = []
    open_t: dict | None = None

    for i in range(WARMUP, n):
        c = trig[i]
        # advance confirmed-level cursors (strictly < i already via confirmed_at)
        while hi_cur < len(highs) and highs[hi_cur][0] <= i:
            last_high = highs[hi_cur][1]; all_high_prices.append(highs[hi_cur][1]); hi_cur += 1
        while lo_cur < len(lows) and lows[lo_cur][0] <= i:
            last_low = lows[lo_cur][1]; all_low_prices.append(lows[lo_cur][1]); lo_cur += 1

        if open_t is not None:
            side, e, stop, tgt = open_t["side"], open_t["entry"], open_t["stop"], open_t["target"]
            if side == "LONG":
                open_t["mae"] = min(open_t["mae"], c.low / e - 1)
                hit_stop, hit_tgt = c.low <= stop, c.high >= tgt
            else:
                open_t["mae"] = min(open_t["mae"], (e - c.high) / e)
                hit_stop, hit_tgt = c.high >= stop, c.low <= tgt
            exit_px = reason = None
            if hit_stop:                      # stop-first on ambiguous bars
                exit_px, reason = stop, "stop"
            elif hit_tgt:
                exit_px, reason = tgt, "target"
            if exit_px is not None:
                gross = (exit_px / e - 1) if side == "LONG" else (e - exit_px) / e
                sd = open_t["stop_dist_frac"]
                open_t.update(exit_ts=_utc(c.close_time_ms), exit_px=exit_px,
                              net_pct=(gross - 2 * FEE) * 100,
                              r_multiple=(gross - 2 * FEE) / sd,
                              bars_held=i - open_t["entry_i"], exit_reason=reason)
                trades.append(open_t); open_t = None
            continue

        # flat: breakout entry check
        bj = bisect_right(bias_ms, c.close_time_ms) - 1
        bias = bias_signs[bj] if bj >= 0 else 0
        if bias == 0 or i < ATR_PERIOD or atr[i] <= 0 or vol_avg[i] <= 0:
            continue
        if not (vols[i] >= vol_mult * vol_avg[i] and vols[i] >= floor):
            continue
        prev, close = trig[i - 1].close, c.close
        side = level = None
        if bias == 1 and last_high is not None and prev <= last_high < close:
            side, level = "LONG", last_high
        elif bias == -1 and last_low is not None and prev >= last_low > close:
            side, level = "SHORT", last_low
        if side is None:
            continue
        buf = STOP_BUFFER_ATR * atr[i]
        stop = level - buf if side == "LONG" else level + buf
        sd_price = abs(close - stop)
        if sd_price <= 0:
            continue
        if target == "2r":
            tgt = close + 2 * sd_price if side == "LONG" else close - 2 * sd_price
        else:  # structural — nearest confirmed swing beyond entry, R:R >= 2
            if side == "LONG":
                above = [p for p in all_high_prices if p > close]
                tgt = min(above) if above else None
            else:
                below = [p for p in all_low_prices if p < close]
                tgt = max(below) if below else None
            if tgt is None or abs(tgt - close) / sd_price < MIN_RR:
                open_t = None
                continue
        open_t = {"side": side, "entry_i": i, "entry": close, "entry_ts": _utc(c.close_time_ms),
                  "level": level, "stop": stop, "target": tgt,
                  "stop_dist_frac": sd_price / close, "mae": 0.0}
    return trades


def summarize(trades: list[dict], structural_skips: int = 0) -> dict:
    if not trades:
        return {"trades": 0, "structural_skips": structural_skips}
    rs = [t["r_multiple"] for t in trades]
    wins = [t for t in trades if t["net_pct"] > 0]
    losses = [t for t in trades if t["net_pct"] <= 0]
    eq = peak = maxdd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); maxdd = max(maxdd, peak - eq)
    gw = sum(t["r_multiple"] for t in wins)
    gl = abs(sum(t["r_multiple"] for t in losses))
    return {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "net_r": round(sum(rs), 2), "pf": round(gw / gl, 2) if gl > 0 else None,
        "win_rate": round(len(wins) / len(trades), 2),
        "worst_mae_pct": round(min(t["mae"] for t in trades) * 100, 2),
        "max_dd_r": round(maxdd, 2),
        "exit_reasons": {r: sum(1 for t in trades if t["exit_reason"] == r)
                         for r in ("stop", "target")},
    }


def phase_run() -> None:
    now = int(time.time() * 1000)
    span = lambda tf: 5100 * interval_seconds(tf) * 1000
    trig_cache, floors, bias_cache = {}, {}, {}
    for tf in TRIGGER_TFS:
        trig_cache[tf] = fetch_candles("BTC", tf, now - span(tf), now)
        floors[tf] = volume_floor(trig_cache[tf])
        c4 = fetch_candles("BTC", "4h", trig_cache[tf][0].close_time_ms - span("4h"), now)
        for m in BIAS_METHODS:
            bias_cache[(tf, m)] = bias_series_4h(c4, m)
        d0 = _utc(trig_cache[tf][0].close_time_ms)[:10]; d1 = _utc(trig_cache[tf][-1].close_time_ms)[:10]
        days = (trig_cache[tf][-1].close_time_ms - trig_cache[tf][0].close_time_ms) / 86400000
        print(f"{tf}: {len(trig_cache[tf])} bars, {days:.0f}d ({d0}..{d1}), vol floor p20={floors[tf]:.1f}")

    results = []
    for m in BIAS_METHODS:
        for tf in TRIGGER_TFS:
            signs, bms = bias_cache[(tf, m)]
            for tgt in TARGETS:
                for vm in VOL_MULTS:
                    trades = run_cell(trig_cache[tf], tf, signs, bms, tgt, vm, floors[tf])
                    s = summarize(trades)
                    results.append({"bias": m, "tf": tf, "target": tgt, "vol_mult": vm,
                                    "under_powered": tf == "15m", "summary": s, "trades": trades})
                    flag = " [15m thin]" if tf == "15m" else ""
                    print(f"{m:5} {tf:3} tgt={tgt:10} vx{vm}: trades {s['trades']:2d} "
                          + (f"W-L {s['wins']}-{s['losses']} netR {s['net_r']:+6.2f} "
                             f"PF {s['pf']} wr {s['win_rate']} maxDD {s['max_dd_r']}R "
                             f"worstMAE {s['worst_mae_pct']}%" if s['trades'] else "") + flag)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "floors": floors, "cells": len(results), "results": results},
                              indent=1), encoding="utf-8")
    print(f"\nwritten: {OUT} ({len(results)} cells)")


def _bar(i, close, spread=0.3):
    return Candle(i * 1000, i * 1000 + 999, close, close + spread,
                  close - spread, close, 100.0)


def _long_series():
    """Clean interpolated zigzag: alternating pivots with unique values (no
    ties) make each anchor a clean fractal extreme. Last confirmed swing high
    is 105 at index 48; a pullback to 56, a monotone rise to ~104 (< 105, no
    new high), then the caller sets a volume breakout at 70 running to a 2R
    target. Guarantees detect_swings sees exactly the intended structure."""
    anchors = [(0, 100.0), (8, 97.0), (16, 101.5), (24, 98.0), (32, 102.5),
               (40, 99.5), (48, 105.0), (56, 101.0), (69, 104.0)]
    px = [0.0] * 80
    for (i0, p0), (i1, p1) in zip(anchors, anchors[1:]):
        for j in range(i0, i1 + 1):
            px[j] = p0 + (p1 - p0) * (j - i0) / (i1 - i0)
    for i in range(70, 80):
        px[i] = 106.0 + (i - 70) * 0.7
    return [_bar(i, px[i]) for i in range(80)]


def phase_selfcheck() -> None:
    signs = [1] * 80
    cs = _long_series()
    cs[70] = Candle(70 * 1000, 70 * 1000 + 999, 104.5, 106.2, 104.3, 106, 5000.0)  # breakout + volume
    bms = [c.close_time_ms for c in cs]
    trades = run_cell(cs, "1h", signs, bms, "2r", 2.0, 50.0)
    assert trades and trades[0]["side"] == "LONG", trades
    # level = the swing bar's HIGH (anchor 105.0 + 0.3 spread) — the resistance broken
    assert 105.2 < trades[0]["level"] < 105.4, trades[0]["level"]
    assert trades[0]["exit_reason"] == "target" and trades[0]["r_multiple"] > 1.5
    assert abs(trades[0]["target"] - (trades[0]["entry"] + 2 * (trades[0]["entry"] - trades[0]["stop"]))) < 1e-6

    # volume floor gates (below absolute floor)
    cs2 = list(cs); cs2[70] = Candle(70000, 70999, 104.5, 106.2, 104.3, 106, 40.0)
    assert run_cell(cs2, "1h", signs, bms, "2r", 2.0, 50.0) == []
    # conviction gates (above floor, below mult*trailing-avg)
    cs3 = list(cs); cs3[70] = Candle(70000, 70999, 104.5, 106.2, 104.3, 106, 120.0)
    assert run_cell(cs3, "1h", signs, bms, "2r", 2.0, 50.0) == []
    # bias DOWN blocks the long breakout
    assert run_cell(cs, "1h", [-1] * 80, bms, "2r", 2.0, 50.0) == []

    # stop-first: breakout then collapse back through the level -> stop loss
    cs4 = list(cs)
    for i in range(71, 80):
        cs4[i] = _bar(i, 100.0)
    t4 = run_cell(cs4, "1h", signs, bms, "2r", 2.0, 50.0)
    assert t4 and t4[0]["exit_reason"] == "stop" and t4[0]["r_multiple"] < 0

    # short mirror
    cd = _long_series()
    px_mirror = [200 - c.close for c in cd]
    cd = [_bar(i, px_mirror[i]) for i in range(80)]
    cd[70] = Candle(70000, 70999, 95.5, 95.7, 93.8, 94, 5000.0)
    td = run_cell(cd, "1h", [-1] * 80, [c.close_time_ms for c in cd], "2r", 2.0, 50.0)
    assert td and td[0]["side"] == "SHORT" and td[0]["exit_reason"] == "target", td

    # no-lookahead: entry fields unchanged when future bars are appended
    base = run_cell(cs[:74], "1h", signs[:74], bms[:74], "2r", 2.0, 50.0)
    full = run_cell(cs, "1h", signs, bms, "2r", 2.0, 50.0)
    assert base and full[0]["entry_i"] == base[0]["entry_i"] and full[0]["entry"] == base[0]["entry"]
    print("selfcheck: all assertions passed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--phase", required=True, choices=("selfcheck", "run"))
    args = ap.parse_args()
    phase_selfcheck() if args.phase == "selfcheck" else phase_run()


if __name__ == "__main__":
    main()
