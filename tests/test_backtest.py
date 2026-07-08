"""Backtest harness acceptance tests: touch-based exits, stop-first
ambiguity rule, fee math, no-lookahead bias slicing, unresolved handling,
sweep expansion, and real return-stats computation."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from backtest import (
    TAKER_FEE,
    bias_slice_no_lookahead,
    expand_sweep,
    log_return_stats,
    simulate_outcome,
)
from data.feed import Candle
from strategy.signals import Signal, SignalDirection

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)


def candle(i, o, h, l, c):
    return Candle(open_time_ms=i * 3600000, close_time_ms=(i + 1) * 3600000,
                  open=o, high=h, low=l, close=c, volume=100)


def long_signal(entry=100.0, stop=95.0, target=110.0):
    return Signal(direction=SignalDirection.LONG, entry=entry, stop=stop, target=target,
                  reward_risk=(target - entry) / (entry - stop), timestamp=NOW,
                  bias_reason="t", trigger_reason="t")


def test_target_touch_wins_two_r_minus_fees():
    candles = [candle(0, 100, 101, 99, 100),        # entry bar (i=0)
               candle(1, 100, 105, 99, 104),        # neither touched
               candle(2, 104, 111, 103, 110)]       # high >= 110 target
    t = simulate_outcome(candles, 0, long_signal())
    assert t.exit_reason == "target"
    assert t.gross_r == pytest.approx(2.0)          # (110-100)/5
    expected_fee_r = (100 + 110) * TAKER_FEE / 5
    assert t.net_r == pytest.approx(2.0 - expected_fee_r)
    assert t.bars_held == 2


def test_stop_touch_loses_one_r_plus_fees():
    candles = [candle(0, 100, 101, 99, 100),
               candle(1, 100, 102, 94, 96)]          # low <= 95 stop
    t = simulate_outcome(candles, 0, long_signal())
    assert t.exit_reason == "stop"
    assert t.gross_r == pytest.approx(-1.0)
    assert t.net_r < -1.0                            # fees make losses worse


def test_ambiguous_candle_assumes_stop_first():
    candles = [candle(0, 100, 101, 99, 100),
               candle(1, 100, 115, 90, 100)]         # touches BOTH stop and target
    t = simulate_outcome(candles, 0, long_signal())
    assert t.exit_reason == "stop"                   # conservative rule


def test_short_direction_mirrored():
    sig = Signal(direction=SignalDirection.SHORT, entry=100.0, stop=105.0, target=90.0,
                 reward_risk=2.0, timestamp=NOW, bias_reason="t", trigger_reason="t")
    candles = [candle(0, 100, 101, 99, 100),
               candle(1, 100, 101, 89, 92)]          # low <= 90 target for short
    t = simulate_outcome(candles, 0, sig)
    assert t.exit_reason == "target"
    assert t.gross_r == pytest.approx(2.0)


def test_unresolved_when_data_ends():
    candles = [candle(0, 100, 101, 99, 100),
               candle(1, 100, 103, 98, 101)]         # never touches either
    t = simulate_outcome(candles, 0, long_signal())
    assert t.exit_reason == "unresolved"
    assert t.gross_r is None and t.net_r is None


def test_bias_slice_never_looks_ahead():
    bias = [candle(i, 100, 101, 99, 100) for i in range(10)]   # closes at (i+1)h
    trigger_close_ms = 5 * 3600000                             # t=5h
    sliced = bias_slice_no_lookahead(bias, trigger_close_ms)
    assert len(sliced) == 5                                    # bars closed at 1h..5h only
    assert all(c.close_time_ms <= trigger_close_ms for c in sliced)


# ── sweep expansion ──

def test_expand_sweep_cross_product_and_multipliers():
    cfg = {"grids": [{
        "name": "A",
        "tf_pairs": [{"bias": "4h", "trigger": "1h"}, {"bias": "1d", "trigger": "4h"}],
        "indicator_sets": ["default", "all"],
        "stop_models": [{"model": "structural"},
                        {"model": "hybrid", "atr_multiplier": 1.5}],
    }]}
    combos = expand_sweep(cfg)
    assert len(combos) == 2 * 2 * 2
    structural = [c for c in combos if c["stop_model"] == "structural"]
    hybrid = [c for c in combos if c["stop_model"] == "hybrid"]
    assert all(c["atr_multiplier"] is None for c in structural)
    assert all(c["atr_multiplier"] == 1.5 for c in hybrid)


def test_expand_sweep_rejects_bad_entries():
    with pytest.raises(SystemExit):                            # hybrid needs a multiplier
        expand_sweep({"grids": [{"name": "A",
                                 "tf_pairs": [{"bias": "4h", "trigger": "1h"}],
                                 "indicator_sets": ["default"],
                                 "stop_models": [{"model": "hybrid"}]}]})
    with pytest.raises(ValueError):                            # bias must exceed trigger
        expand_sweep({"grids": [{"name": "A",
                                 "tf_pairs": [{"bias": "1h", "trigger": "4h"}],
                                 "indicator_sets": ["default"],
                                 "stop_models": [{"model": "structural"}]}]})


def test_shipped_sweep_config_expands():
    import pathlib

    import yaml
    path = pathlib.Path(__file__).resolve().parent.parent / "sweep_config.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    combos = expand_sweep(cfg)
    assert len(combos) >= 36                                   # Grid A: 3 TF x 3 ind x 4 stop
    assert {c["grid"] for c in combos} >= {"A_stop_models"}


# ── return statistics (real data replaces the rejected external table) ──

def test_log_return_stats_alternating_series():
    closes = [100.0, 110.0, 100.0]                             # rets: +ln1.1, -ln1.1
    candles = [candle(i, c, c, c, c) for i, c in enumerate(closes)]
    stats = log_return_stats(candles)
    r = math.log(1.1)
    assert stats["n"] == 2
    assert stats["mean"] == pytest.approx(0.0)
    assert stats["stdev"] == pytest.approx(r * math.sqrt(2))   # sample stdev, n-1
    assert stats["excess_kurtosis"] == pytest.approx(-2.0)     # two-point symmetric dist


def test_log_return_stats_insufficient():
    assert log_return_stats([candle(0, 100, 100, 100, 100)]) == {"n": 0}
