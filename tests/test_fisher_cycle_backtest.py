"""Track 3 Part 3 — fisher-cycle simulator orchestration.

Drives run_fisher_cycle_backtest over hand-built 4H candles with the
Fisher line, ATR, and 1D bias monkeypatched to controlled sequences, so
each state transition (exhaustion flip, stop → flat-and-rearm, macro
force-flatten) is exercised deterministically. Fee math and per-cycle
cumulative R are asserted from the emitted legs."""
from __future__ import annotations

import backtest as bt
from data.feed import Candle
from strategy.bias_4h import Bias

H4 = 4 * 3600 * 1000
TAKER = bt.TAKER_FEE


def bar(i, close, high=None, low=None):
    return Candle(open_time_ms=i * H4, close_time_ms=(i + 1) * H4,
                  open=close, high=high if high is not None else close + 0.2,
                  low=low if low is not None else close - 0.2, close=close, volume=100.0)


def _patch(monkeypatch, fisher, atr, bias_fn):
    monkeypatch.setattr(bt, "WARMUP_TRIGGER_BARS", 0)
    monkeypatch.setattr(bt, "fisher_transform", lambda candles: (list(fisher), []))
    monkeypatch.setattr(bt, "wilder_atr", lambda candles: [atr] * len(candles))
    monkeypatch.setattr(bt, "daily_bias_at", lambda daily, ts: bias_fn(ts))


def _fee_r(entry, exit_, risk):
    return (entry + exit_) * TAKER / risk


def test_full_cycle_long_flip_short_flip_long(monkeypatch):
    closes = [100, 100, 105, 110, 108, 105]
    fisher = [-0.5, -2.5, 0.5, 2.5, 0.5, -2.5]
    candles = [bar(i, c) for i, c in enumerate(closes)]
    _patch(monkeypatch, fisher, atr=1.0, bias_fn=lambda ts: Bias.BULLISH)

    summary = bt.run_fisher_cycle_backtest([], candles, exhaustion_threshold=2.0, atr_multiplier=1.0)
    legs = summary["trades"]

    assert [l.direction for l in legs] == ["LONG", "SHORT", "LONG"]
    assert [l.exit_reason for l in legs] == ["exhaustion_flip", "exhaustion_flip", "unresolved"]
    assert {l.indicators_snapshot["cycle_id"] for l in legs} == {1}   # one macro cycle
    assert summary["cycles"]["count"] == 1

    # leg1 long: entry 100 -> flip-exit 110, risk = atr*mult = 1.0
    assert legs[0].gross_r == 10.0
    assert legs[0].net_r == 10.0 - _fee_r(100, 110, 1.0)
    # leg2 short: entry 110 -> flip-exit 105 (price fell -> short profits)
    assert legs[1].gross_r == 5.0
    assert legs[1].net_r == 5.0 - _fee_r(110, 105, 1.0)
    # leg3 unresolved -> no R
    assert legs[2].net_r is None
    # cumulative cycle R = resolved legs only
    assert summary["cycles"]["cumulative_r_per_cycle"] == [
        round(legs[0].net_r + legs[1].net_r, 4)]


def test_stop_goes_flat_and_rearms_long_not_flip(monkeypatch):
    closes = [100, 100, 98, 100, 100]
    fisher = [-0.5, -2.5, -0.5, -0.5, -2.5]
    candles = [bar(i, c) for i, c in enumerate(closes)]
    candles[2] = bar(2, 98, high=98.2, low=97.5)     # low 97.5 breaches long stop 99
    _patch(monkeypatch, fisher, atr=1.0, bias_fn=lambda ts: Bias.BULLISH)

    summary = bt.run_fisher_cycle_backtest([], candles, exhaustion_threshold=2.0, atr_multiplier=1.0)
    legs = summary["trades"]

    # leg1 long opened at i=1 (100), stopped at i=2; NOT flipped to short
    assert legs[0].direction == "LONG" and legs[0].exit_reason == "stop"
    assert legs[0].entry == 100.0 and legs[0].stop == 99.0
    assert legs[0].gross_r == -1.0                    # exit at stop, risk 1.0
    # re-arm: next qualifying oversold bar reopens a LONG at i=4 (same cycle),
    # NOT the same bar as the stop (i=2), and never a SHORT
    assert [l.direction for l in legs] == ["LONG", "LONG"]
    # re-armed leg entered at bar 4's close (5*H4), NOT bar 2 (the stop bar)
    assert legs[1].entry_ts.timestamp() * 1000 == 5 * H4
    assert legs[1].exit_reason == "unresolved"
    assert {l.indicators_snapshot["cycle_id"] for l in legs} == {1}
    assert all(l.direction != "SHORT" for l in legs)


def test_macro_flip_force_flattens_and_ends_cycle(monkeypatch):
    closes = [100, 100, 105, 104]
    fisher = [-0.5, -2.5, -0.5, -0.5]
    candles = [bar(i, c) for i, c in enumerate(closes)]
    # bias bullish through i=2's close (ts <= 3*H4), bearish after
    _patch(monkeypatch, fisher, atr=1.0,
           bias_fn=lambda ts: Bias.BULLISH if ts <= 3 * H4 else Bias.BEARISH)

    summary = bt.run_fisher_cycle_backtest([], candles, exhaustion_threshold=2.0, atr_multiplier=1.0)
    legs = summary["trades"]

    assert len(legs) == 1
    assert legs[0].direction == "LONG" and legs[0].exit_reason == "bias_flip"
    assert legs[0].exit_ts.timestamp() * 1000 == 4 * H4     # flattened at i=3 close
    # bias is now BEARISH; a bearish cycle opens SHORT only at Fisher>=+2,
    # and fisher is -0.5 -> no reopen
    assert summary["cycles"]["count"] == 1
