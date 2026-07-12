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
from strategy.bias_4h import Bias
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
    # no target_models key -> baseline target model everywhere
    assert all(c["target_model"] == "nearest_structure" for c in combos)
    assert all(c["blue_sky_atr_multiplier"] is None for c in combos)


def test_expand_sweep_target_model_axis():
    cfg = {"grids": [{
        "name": "C",
        "tf_pairs": [{"bias": "4h", "trigger": "1h"}],
        "indicator_sets": ["default"],
        "stop_models": [{"model": "structural"}],
        "target_models": ["nearest_structure", "fib_extension_preferred", "blue_sky_atr"],
        "blue_sky_atr_multiplier": 3.0,
    }]}
    combos = expand_sweep(cfg)
    assert [c["target_model"] for c in combos] == [
        "nearest_structure", "fib_extension_preferred", "blue_sky_atr"]
    # multiplier only attaches to the blue-sky model
    assert [c["blue_sky_atr_multiplier"] for c in combos] == [None, None, 3.0]
    with pytest.raises(SystemExit):
        expand_sweep({"grids": [{"name": "C", "tf_pairs": [{"bias": "4h", "trigger": "1h"}],
                                 "indicator_sets": ["default"],
                                 "stop_models": [{"model": "structural"}],
                                 "target_models": ["moonshot"]}]})


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
    assert len(combos) == 27                    # Grid C: 3 TF x 3 stop x 3 target
    assert {c["grid"] for c in combos} == {"C_targets"}
    assert {c["target_model"] for c in combos} == set(
        ("nearest_structure", "fib_extension_preferred", "blue_sky_atr"))
    assert all(not c["fisher4h_entry"] and not c["fisher4h_exit"] for c in combos)


# ── 4H Fisher exhaustion exit (backtest-only V2.2 variant) ──

H = 3600000


def _drift_candles(n, start=100.0):
    """Never touches the test signal's stop (95) or target (120)."""
    return [candle(i, start, start + 2, start - 2, start) for i in range(n)]


def test_fisher_exhaustion_exit_on_cross_in_favor():
    candles = _drift_candles(10)
    # 4h bars close at 4h and 8h; Fisher crosses INTO +2 territory at 8h
    series = [(4 * H, 1.0), (8 * H, 2.5)]
    t = simulate_outcome(candles, 0, long_signal(entry=100.0, stop=95.0, target=120.0),
                         fisher4h_exit=True, fisher4h_series=series,
                         exhaustion_threshold=2.0)
    assert t.exit_reason == "fisher_exhaustion"
    assert t.bars_held == 7                                    # bar closing at 8h is index 7
    assert t.exit_ts == datetime.fromtimestamp(8 * 3600, tz=timezone.utc)
    exit_price = candles[7].close                              # exit AT the trigger close
    expected_gross = (exit_price - 100.0) / 5.0
    expected_fee = (100.0 + exit_price) * TAKER_FEE / 5.0
    assert t.gross_r == pytest.approx(expected_gross)
    assert t.net_r == pytest.approx(expected_gross - expected_fee)


def test_fisher_exhaustion_edge_semantics_already_extended_never_fires():
    candles = _drift_candles(12)
    # extended BEFORE entry (4h close <= entry close) and stays extended:
    # no crossing INTO the zone after entry -> no exit
    series = [(4 * H, 2.3), (8 * H, 2.4), (12 * H, 2.2)]
    t = simulate_outcome(candles, 4, long_signal(entry=100.0, stop=95.0, target=120.0),
                         fisher4h_exit=True, fisher4h_series=series,
                         exhaustion_threshold=2.0)
    assert t.exit_reason == "unresolved"


def test_fisher_exhaustion_stop_touch_same_bar_wins():
    candles = _drift_candles(10)
    candles[7] = candle(7, 100, 102, 94, 96)                   # touches stop at bar 7 (close 8h)
    series = [(4 * H, 1.0), (8 * H, 2.5)]                      # cross also lands at 8h
    t = simulate_outcome(candles, 0, long_signal(entry=100.0, stop=95.0, target=120.0),
                         fisher4h_exit=True, fisher4h_series=series,
                         exhaustion_threshold=2.0)
    assert t.exit_reason == "stop"                             # touch precedes close-based exit


def test_fisher_exhaustion_short_mirrored_and_opposite_ignored():
    short = Signal(direction=SignalDirection.SHORT, entry=100.0, stop=105.0, target=80.0,
                   reward_risk=4.0, timestamp=NOW, bias_reason="t", trigger_reason="t")
    candles = _drift_candles(10)
    in_favor = [(4 * H, -1.0), (8 * H, -2.5)]                  # bearish extension favors a short
    t = simulate_outcome(candles, 0, short, fisher4h_exit=True,
                         fisher4h_series=in_favor, exhaustion_threshold=2.0)
    assert t.exit_reason == "fisher_exhaustion"

    against = [(4 * H, 1.0), (8 * H, 2.5)]                     # bullish extension is NOT in favor
    t2 = simulate_outcome(candles, 0, short, fisher4h_exit=True,
                          fisher4h_series=against, exhaustion_threshold=2.0)
    assert t2.exit_reason == "unresolved"


def test_fisher_exhaustion_exit_requires_series():
    with pytest.raises(ValueError):
        simulate_outcome(_drift_candles(5), 0, long_signal(), fisher4h_exit=True)


# ── 4H Fisher exhaustion entry filter (strategy/signals.py) ──

def test_entry_filter_suppresses_same_direction_extension(monkeypatch):
    import strategy.signals as signals_mod
    from strategy.signals import evaluate_signal
    from tests.test_hybrid_stop import BIAS_ONLY, _synthetic_bullish_bias, flat_candles

    monkeypatch.setattr(signals_mod, "compute_bias", lambda c: _synthetic_bullish_bias())
    trigger = flat_candles(30, close=100.0, spread=2.0)

    suppressed = evaluate_signal(trigger, trigger, config=BIAS_ONLY,
                                 fisher4h_entry_filter=True, fisher4h_value=2.3)
    assert type(suppressed).__name__ == "SuppressedSignal"
    assert suppressed.kind == "fisher4h_exhaustion"

    # extension in the OPPOSITE direction must not suppress a long
    taken = evaluate_signal(trigger, trigger, config=BIAS_ONLY,
                            fisher4h_entry_filter=True, fisher4h_value=-2.5)
    assert isinstance(taken, Signal)

    # below threshold -> not extended -> taken
    taken2 = evaluate_signal(trigger, trigger, config=BIAS_ONLY,
                             fisher4h_entry_filter=True, fisher4h_value=1.9)
    assert isinstance(taken2, Signal)

    with pytest.raises(ValueError):                            # filter without a value is a bug
        evaluate_signal(trigger, trigger, config=BIAS_ONLY, fisher4h_entry_filter=True)


# ── no-stop patient-hold exit (spot-capital accumulation variant) ──

def _bull_series(*hours):
    """(close_ms, Bias) step function, BULLISH at each listed hour."""
    return [(h * H, Bias.BULLISH) for h in hours]


def test_patient_hold_reversion_holds_through_stop_no_stopout():
    # Long @100 (stop 95, never placed). Bar 1 wicks to 90 — BELOW the stop —
    # but closes underwater; bar 2 closes green -> first-profit reversion exit.
    candles = [candle(0, 100, 101, 99, 100),
               candle(1, 96, 97, 90, 96),           # low 90 < stop 95, still not profitable
               candle(2, 96, 102, 99, 101)]         # first net-profitable close
    bias = [(0, Bias.BULLISH), (H, Bias.BULLISH), (2 * H, Bias.BULLISH), (3 * H, Bias.BULLISH)]
    t = simulate_outcome(candles, 0, long_signal(entry=100.0, stop=95.0, target=110.0),
                         patient_hold_exit=True, bias4h_series=bias)
    assert t.exit_reason == "reversion"              # NOT "stop" — the wick to 90 is held through
    assert t.bars_held == 2
    assert t.mae_frac == pytest.approx(-0.10)        # deepest dip: (90-100)/100
    assert t.mae_r == pytest.approx(-2.0)            # -0.10 * 100 / risk(5)
    assert t.net_r > 0


def test_patient_hold_bias_flip_exit_while_underwater():
    # Long @100 stays underwater; 4H bias flips BEARISH at bar 2 -> force-flatten.
    candles = [candle(0, 100, 101, 99, 100),
               candle(1, 98, 99, 97, 98),
               candle(2, 98, 99, 96, 97)]
    bias = [(0, Bias.BULLISH), (H, Bias.BULLISH), (2 * H, Bias.BULLISH), (3 * H, Bias.BEARISH)]
    t = simulate_outcome(candles, 0, long_signal(entry=100.0, stop=95.0, target=110.0),
                         patient_hold_exit=True, bias4h_series=bias)
    assert t.exit_reason == "bias_flip"
    assert t.bars_held == 2
    assert t.net_r < 0                               # flattened at a loss (no stop, no profit)
    assert t.mae_frac < 0


def test_patient_hold_neutral_bias_counts_as_invalidation():
    # NEUTRAL is not the opened (BULLISH) direction -> invalidation, per macro_broken.
    candles = [candle(0, 100, 101, 99, 100),
               candle(1, 99, 100, 98, 99)]
    bias = [(0, Bias.BULLISH), (H, Bias.BULLISH), (2 * H, Bias.NEUTRAL)]
    t = simulate_outcome(candles, 0, long_signal(entry=100.0, stop=95.0, target=110.0),
                         patient_hold_exit=True, bias4h_series=bias)
    assert t.exit_reason == "bias_flip"


def test_patient_hold_short_mirrored_holds_through_stop():
    # Short @100 (stop 105, never placed). Bar 1 wicks to 112 — ABOVE the stop —
    # held; bar 2 closes green for the short -> reversion.
    short = Signal(direction=SignalDirection.SHORT, entry=100.0, stop=105.0, target=90.0,
                   reward_risk=2.0, timestamp=NOW, bias_reason="t", trigger_reason="t")
    candles = [candle(0, 100, 101, 99, 100),
               candle(1, 104, 112, 103, 104),        # high 112 > stop 105, underwater for short
               candle(2, 104, 105, 97, 98)]          # short in profit at close
    bias = [(0, Bias.BEARISH), (H, Bias.BEARISH), (2 * H, Bias.BEARISH), (3 * H, Bias.BEARISH)]
    t = simulate_outcome(candles, 0, short, patient_hold_exit=True, bias4h_series=bias)
    assert t.exit_reason == "reversion"
    assert t.mae_frac == pytest.approx(-0.12)        # (100-112)/100
    assert t.mae_r == pytest.approx(-2.4)            # -0.12 * 100 / risk(5)


def test_patient_hold_unresolved_when_data_ends():
    candles = [candle(0, 100, 101, 99, 100),
               candle(1, 98, 99, 97, 98)]            # underwater, bias holds -> never exits
    t = simulate_outcome(candles, 0, long_signal(entry=100.0, stop=95.0, target=110.0),
                         patient_hold_exit=True, bias4h_series=_bull_series(0, 1, 2, 3))
    assert t.exit_reason == "unresolved"
    assert t.gross_r is None and t.net_r is None
    assert t.mae_frac < 0                            # MAE still reported for an open hostage


def test_patient_hold_requires_bias_series():
    with pytest.raises(ValueError):
        simulate_outcome([candle(0, 100, 101, 99, 100), candle(1, 100, 103, 98, 101)],
                         0, long_signal(), patient_hold_exit=True)


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
