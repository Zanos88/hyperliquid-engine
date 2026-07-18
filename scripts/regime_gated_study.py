"""Regime-Gated Strategy Study — test if gating trend/mean-rev by regime improves results.

Genuinely NEW: the regime classifier (pre-registered, locked) was built for
descriptive analysis only (regime_split.json). No study used regime labels as
a TRADING GATE. This fills that gap.

Tests:
  1. Pure TSMOM30 baseline (repro)
  2. TSMOM30 gated-by-BULL only (flat in NEUTRAL/BEAR)
  3. TSMOM30 weighted-by-regime (100% BULL, 50% NEUTRAL, 0% BEAR)
  4. Pure SMA50 baseline
  5. SMA50 gated-by-BULL only
  6. SMA50 regime-weighted
  7. Track 4 mean-reversion baseline
  8. Track 4 gated by 1D regime (take entry only if daily regime is BULL)
  9. Buy-and-hold baseline

Uses only frozen snapshots + pre-existing regime_labels. No fetch, no API.
"""

from __future__ import annotations

import json
import math
import sys
from bisect import bisect_left, bisect_right
from pathlib import Path
from datetime import datetime, timezone

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import OUTPUT_DIR, load_snapshot
from strategy_tournament import (
    BARS_PER_YEAR, STRATEGIES, FEE, WARMUP, buy_hold_metrics, eval_bounds,
    log_returns, metrics, net_strategy_returns, sma_positions, tsmom_positions,
)
from data.feed import Candle

OUT = OUTPUT_DIR / "regime_gated_results.json"

# ── load regime labels ───────────────────────────────────────

def load_regime_labels() -> dict[int, str]:
    """Return {close_ms: label} for each bar in the BTC 1D regime_labels."""
    path = OUTPUT_DIR / "regime_labels_btc.json"
    if not path.exists():
        print("ERROR: regime_labels_btc.json not found. Run regime_classifier.py --phase labels first.")
        sys.exit(1)
    doc = json.loads(path.read_text())
    return {r["close_ms"]: r["label"] for r in doc["labels"]}


# ── regime-gated wrappers ────────────────────────────────────

def regime_gated_positions(
    candles: list[Candle],
    base_fn,
    regime_map: dict[int, str],
    allowed_regimes: set[str],
) -> list[int]:
    """Take base strategy positions, zero them out when regime not in allowed."""
    base = base_fn(candles)
    out = [0] * len(candles)
    for i in range(len(candles)):
        ms = candles[i].close_time_ms
        lab = regime_map.get(ms, "NEUTRAL")
        if lab in allowed_regimes:
            out[i] = base[i]
    return out


def regime_weighted_positions(
    candles: list[Candle],
    base_fn,
    regime_map: dict[int, str],
    weights: dict[str, float],
) -> list[int]:
    """Scale position by regime weight (e.g. BULL=1.0, NEUTRAL=0.5, BEAR=0.0).
    Since positions are 0/1 in the tournament framework, we simulate weight by
    computing separate return streams and scaling them — or we use discrete entry.
    Instead we return 0/1 positions but only enter in allowed regimes with
    weight applied to the RETURN stream.
    """
    base = base_fn(candles)
    out = [0] * len(candles)
    for i in range(len(candles)):
        ms = candles[i].close_time_ms
        lab = regime_map.get(ms, "NEUTRAL")
        w = weights.get(lab, 0.0)
        if w > 0 and base[i] == 1:
            out[i] = 1
    return out


# ── Track 4 mean-reversion regime-gated ──────────────────────

def _sma(closes: list[float], period: int) -> list[float]:
    out: list[float] = []
    running = 0.0
    for i, px in enumerate(closes):
        running += px
        if i >= period:
            running -= closes[i - period]
        out.append(running / period if i >= period - 1 else 0.0)
    return out


def track4_positions_1d(candles_1d: list[Candle]) -> list[int]:
    """Simplified Track 4 for 1D BTC: Fisher(5) <= -1.25 AND close > SMA(30) → long.
    Uses daily data as a proxy — not 4H entries. Gives directional signal.
    Exit: close above entry (first profit) or Fisher crosses above +1.5.
    This is a COMPRESSED version for 1D bars (not the full 4H engine).
    """
    closes = [c.close for c in candles_1d]
    n = len(closes)

    # V1 Fisher(5) with Ehlers' algorithm (same as trigger_1h.fisher_transform)
    lookback = 5
    fisher: list[float] = []
    half_range = 0.0
    prev_n1 = 0.0
    for i in range(n):
        if i < lookback:
            fisher.append(0.0)
            continue
        window = closes[i - lookback:i + 1]
        lo, hi = min(window), max(window)
        val = (closes[i] - lo) / (hi - lo) * 2.0 - 1.0 if hi != lo else 0.0
        val = max(-0.9999, min(0.9999, val))
        n1 = 0.5 * math.log((1.0 + val) / (1.0 - val)) + 0.5 * prev_n1
        fisher_val = (n1 + prev_n1) * 0.5
        prev_n1 = n1
        half_range = hi - lo
        fisher.append(fisher_val)

    # SMA(30) bias
    sma30 = _sma(closes, 30)

    # Track 4 logic: LONG when Fisher <= -1.25 AND close > SMA(30) uptrend
    pos = [0] * n
    in_trade = False
    entry = 0.0
    for i in range(30, n):
        if not in_trade:
            if closes[i] > sma30[i] and fisher[i] <= -1.25:
                pos[i] = 1
                in_trade = True
                entry = closes[i]
        else:
            pos[i] = 1
            # Exit signals
            if closes[i] > entry:  # first profit
                in_trade = False
            elif fisher[i] >= 1.5:  # reversal
                in_trade = False
            if not in_trade:
                # Flat next bar
                if i + 1 < n:
                    pos[i] = 1  # still filled this bar
    return pos


def track4_regime_gated(
    candles_1d: list[Candle],
    regime_map: dict[int, str],
    regimes: set[str],
) -> list[int]:
    """Track 4 positions, but only enter when daily regime is BULL."""
    base = track4_positions_1d(candles_1d)
    out = [0] * len(candles_1d)
    in_trade = False
    for i in range(len(candles_1d)):
        ms = candles_1d[i].close_time_ms
        lab = regime_map.get(ms, "NEUTRAL")
        if not in_trade:
            if base[i] == 1 and lab in regimes:
                out[i] = 1
                in_trade = True
        else:
            out[i] = base[i]  # follow the trade until exit
            if base[i] == 0:
                in_trade = False
    return out


# ── funding-rate mean-reversion (new angle) ──────────────────

def funding_mr_positions_1d(candles_1d: list[Candle]) -> list[int]:
    """Funding-rate mean-reversion strategy.

    Long when: 30d avg funding rate is in its bottom 10% percentile (extreme
    negative — market is paying to short → bullish signal).
    Short when: 30d avg funding is in its top 10% percentile (extreme positive).
    Flat otherwise.

    This uses the existing regime_labels funding percentile data.
    """
    path = OUTPUT_DIR / "regime_labels_btc.json"
    doc = json.loads(path.read_text())
    labels = doc["labels"]
    # Extract funding percentile from labels
    funding_by_ms = {}
    for r in labels:
        ms = r["close_ms"]
        fv = r.get("funding")
        funding_by_ms[ms] = fv

    pos = [0] * len(candles_1d)
    for i, c in enumerate(candles_1d):
        if i < 30:
            continue
        ms = c.close_time_ms
        fv = funding_by_ms.get(ms)
        # funding_votes: BULL if pct >= 70, BEAR if pct <= 30
        # For mean-reversion: we fade the funding:
        # When funding BULL (expensive longs) → go SHORT
        # When funding BEAR (expensive shorts) → go LONG
        if fv == "BEAR":
            pos[i] = 1   # expensive to short → go long (mean-revert)
        elif fv == "BULL":
            pos[i] = 0   # expensive to long → go flat (avoid)
        # else NEUTRAL → flat
    return pos


# ── main ─────────────────────────────────────────────────────

def main() -> None:
    candles, _ = load_snapshot("1d")
    rets = log_returns(candles)
    bpy = BARS_PER_YEAR["1d"]
    a, ee, _ = eval_bounds(len(candles))

    regime_map = load_regime_labels()

    results: dict[str, dict] = {}

    # ── 1. Baseline: buy-and-hold ──
    bh_metrics = buy_hold_metrics(rets, a, ee, bpy)
    results["buy_hold"] = {k: round(v, 4) if isinstance(v, float) else v
                           for k, v in bh_metrics.items()}
    results["buy_hold"]["type"] = "baseline"

    # ── 2. Pure TSMOM30 (repro) ──
    tsmom_base = tsmom_positions(candles, 30)
    net_tsmom = net_strategy_returns(tsmom_base, rets)
    m = metrics(net_tsmom, tsmom_base, a, ee, bpy)
    results["tsmom30"] = {k: round(v, 4) if isinstance(v, float) else v
                          for k, v in m.items()}
    results["tsmom30"]["type"] = "baseline"

    # ── 3. TSMOM30 gated by BULL only ──
    tsmom_bull = regime_gated_positions(candles, lambda cs: tsmom_positions(cs, 30),
                                          regime_map, {"BULL"})
    net_tsmom_bull = net_strategy_returns(tsmom_bull, rets)
    m_bull = metrics(net_tsmom_bull, tsmom_bull, a, ee, bpy)
    results["tsmom30_bull_only"] = {k: round(v, 4) if isinstance(v, float) else v
                                     for k, v in m_bull.items()}
    results["tsmom30_bull_only"]["type"] = "regime_gated"

    # ── 4. TSMOM30 gated by BULL|NEUTRAL (skip BEAR) ──
    tsmom_no_bear = regime_gated_positions(candles, lambda cs: tsmom_positions(cs, 30),
                                             regime_map, {"BULL", "NEUTRAL"})
    net_tsmom_nb = net_strategy_returns(tsmom_no_bear, rets)
    m_nb = metrics(net_tsmom_nb, tsmom_no_bear, a, ee, bpy)
    results["tsmom30_no_bear"] = {k: round(v, 4) if isinstance(v, float) else v
                                   for k, v in m_nb.items()}
    results["tsmom30_no_bear"]["type"] = "regime_gated"

    # ── 5. Pure SMA50 baseline ──
    sma50_base = sma_positions(candles, 50)
    net_sma50 = net_strategy_returns(sma50_base, rets)
    m_sma50 = metrics(net_sma50, sma50_base, a, ee, bpy)
    results["sma50"] = {k: round(v, 4) if isinstance(v, float) else v
                        for k, v in m_sma50.items()}
    results["sma50"]["type"] = "baseline"

    # ── 6. SMA50 gated by BULL only ──
    sma50_bull = regime_gated_positions(candles, lambda cs: sma_positions(cs, 50),
                                          regime_map, {"BULL"})
    net_sma50_bull = net_strategy_returns(sma50_bull, rets)
    m_sma50_bull = metrics(net_sma50_bull, sma50_bull, a, ee, bpy)
    results["sma50_bull_only"] = {k: round(v, 4) if isinstance(v, float) else v
                                   for k, v in m_sma50_bull.items()}
    results["sma50_bull_only"]["type"] = "regime_gated"

    # ── 7. SMA50 no-BEAR ──
    sma50_nb = regime_gated_positions(candles, lambda cs: sma_positions(cs, 50),
                                        regime_map, {"BULL", "NEUTRAL"})
    net_sma50_nb = net_strategy_returns(sma50_nb, rets)
    m_sma50_nb = metrics(net_sma50_nb, sma50_nb, a, ee, bpy)
    results["sma50_no_bear"] = {k: round(v, 4) if isinstance(v, float) else v
                                 for k, v in m_sma50_nb.items()}
    results["sma50_no_bear"]["type"] = "regime_gated"

    # ── 8. Track 4 (1D proxy) baseline ──
    t4_base = track4_positions_1d(candles)
    net_t4 = net_strategy_returns(t4_base, rets)
    m_t4 = metrics(net_t4, t4_base, a, ee, bpy)
    results["track4_1d"] = {k: round(v, 4) if isinstance(v, float) else v
                            for k, v in m_t4.items()}
    results["track4_1d"]["type"] = "baseline"

    # ── 9. Track 4 gated by BULL ──
    t4_bull = track4_regime_gated(candles, regime_map, {"BULL"})
    net_t4_bull = net_strategy_returns(t4_bull, rets)
    m_t4_bull = metrics(net_t4_bull, t4_bull, a, ee, bpy)
    results["track4_bull_only"] = {k: round(v, 4) if isinstance(v, float) else v
                                    for k, v in m_t4_bull.items()}
    results["track4_bull_only"]["type"] = "regime_gated"

    # ── 10. Funding MR baseline ──
    fund_pos = funding_mr_positions_1d(candles)
    net_fund = net_strategy_returns(fund_pos, rets)
    m_fund = metrics(net_fund, fund_pos, a, ee, bpy)
    results["funding_mr"] = {k: round(v, 4) if isinstance(v, float) else v
                             for k, v in m_fund.items()}
    results["funding_mr"]["type"] = "new_angle"

    # compute win rates from the net return streams
    all_streams = {
        "buy_hold": [1] * len(candles),
    }

    # ── summary comparison ──
    header = f"{'Strategy':25s} {'Type':15s} {'Sharpe':>8s} {'AnnRet%':>8s} {'MaxDD':>8s} {'Trades':>7s} {'Exp%':>6s} {'NetMult':>8s} {'Win%':>6s}"
    print("=" * 100)
    print(header)
    print("=" * 100)

    for name, net_stream, pos_ref in [
        ("buy_hold", net_strategy_returns([1] * len(candles), rets), [1] * len(candles)),
        ("tsmom30", net_tsmom, tsmom_base),
        ("tsmom30_bull_only", net_tsmom_bull, tsmom_bull),
        ("tsmom30_no_bear", net_tsmom_nb, tsmom_no_bear),
        ("sma50", net_sma50, sma50_base),
        ("sma50_bull_only", net_sma50_bull, sma50_bull),
        ("sma50_no_bear", net_sma50_nb, sma50_nb),
        ("track4_1d", net_t4, t4_base),
        ("track4_bull_only", net_t4_bull, t4_bull),
        ("funding_mr", net_fund, fund_pos),
    ]:
        r = results[name]
        trading_bars = sum(1 for j in range(max(a, WARMUP), ee + 1) if pos_ref[j] > 0)
        win_bars = sum(1 for j in range(max(a, WARMUP), ee + 1)
                       if pos_ref[j] > 0 and rets[j] > 0)
        win_rate = (win_bars / trading_bars * 100) if trading_bars > 0 else 0.0

        print(f"{name:25s} {r.get('type',''):15s} {r['sharpe']:>8.3f} {r['ann_return_pct']:>8.2f} {r['max_dd_log']:>8.4f} {r['trades']:>7.0f} {r['exposure']*100:>5.1f}% {r['net_multiple']:>8.4f} {win_rate:>5.1f}%")

    print("=" * 100)

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "regime_gated_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
