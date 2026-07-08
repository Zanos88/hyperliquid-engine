"""Hybrid stop acceptance tests: Wilder ATR math, wider-of-two selection
in both directions, structural fallback, default-behavior preservation,
and the R-Drift regression (sizing must consume the FINAL hybrid stop,
never the nominal structural distance)."""
from __future__ import annotations

import pytest

import strategy.signals as signals_mod
from data.feed import Candle
from strategy.atr import wilder_atr
from strategy.bias_4h import Bias, BiasResult, SRLevel
from strategy.signals import (
    Signal,
    SignalDirection,
    evaluate_signal,
    resolve_stop,
)
from risk.sizing import size as compute_size


def candle(i, o, h, lo, c, volume=100.0):
    return Candle(open_time_ms=i * 3600000, close_time_ms=(i + 1) * 3600000,
                  open=o, high=h, low=lo, close=c, volume=volume)


def flat_candles(n, close=100.0, spread=2.0):
    """Constant-range candles: TR = spread every bar, so ATR == spread."""
    return [candle(i, close, close + spread / 2, close - spread / 2, close) for i in range(n)]


# ── Wilder ATR ──

def test_atr_constant_range_equals_range():
    candles = flat_candles(30, close=100.0, spread=2.0)
    atr = wilder_atr(candles, period=14)
    assert atr[13] == 0.0                      # before seed completes
    assert atr[14] == pytest.approx(2.0)       # seed = mean of 14 identical TRs
    assert atr[-1] == pytest.approx(2.0)       # smoothing of a constant is the constant


def test_atr_hand_computed_seed_and_smoothing():
    # period=3: TR1=4 (gap vs prev close), TR2=2, TR3=2 -> seed=(4+2+2)/3=8/3
    # bar 4 TR=5 -> ATR = (8/3 * 2 + 5) / 3 = 31/9
    candles = [
        candle(0, 10, 11, 9, 10),
        candle(1, 10, 14, 10, 12),   # TR = max(4, |14-10|, |10-10|) = 4
        candle(2, 12, 13, 11, 12),   # TR = 2
        candle(3, 12, 13, 11, 12),   # TR = 2
        candle(4, 12, 16, 11, 15),   # TR = 5
    ]
    atr = wilder_atr(candles, period=3)
    assert atr[3] == pytest.approx(8 / 3)
    assert atr[4] == pytest.approx((8 / 3 * 2 + 5) / 3)


def test_atr_insufficient_history_all_zero():
    assert wilder_atr(flat_candles(10), period=14) == [0.0] * 10


# ── resolve_stop: wider-of-two in both directions ──

def test_hybrid_long_picks_wider_atr_floor():
    trigger = flat_candles(30, close=100.0, spread=2.0)   # ATR = 2.0
    # structural stop 99.5 (tight); ATR floor = 100 - 1.5*2 = 97.0 (wider)
    stop = resolve_stop(SignalDirection.LONG, 100.0, 99.5, trigger,
                        stop_model="hybrid", atr_multiplier=1.5)
    assert stop == pytest.approx(97.0)


def test_hybrid_long_keeps_structural_when_already_wider():
    trigger = flat_candles(30, close=100.0, spread=2.0)
    stop = resolve_stop(SignalDirection.LONG, 100.0, 95.0, trigger,
                        stop_model="hybrid", atr_multiplier=1.5)
    assert stop == pytest.approx(95.0)          # structural already beyond the ATR floor


def test_hybrid_short_mirrored():
    trigger = flat_candles(30, close=100.0, spread=2.0)
    # short: wider = HIGHER stop. structural 100.4 vs ATR floor 100 + 3 = 103
    stop = resolve_stop(SignalDirection.SHORT, 100.0, 100.4, trigger,
                        stop_model="hybrid", atr_multiplier=1.5)
    assert stop == pytest.approx(103.0)
    stop2 = resolve_stop(SignalDirection.SHORT, 100.0, 105.0, trigger,
                         stop_model="hybrid", atr_multiplier=1.5)
    assert stop2 == pytest.approx(105.0)


def test_hybrid_falls_back_to_structural_without_atr_history():
    trigger = flat_candles(10)                  # < period+1 -> ATR series all zero
    stop = resolve_stop(SignalDirection.LONG, 100.0, 99.5, trigger,
                        stop_model="hybrid", atr_multiplier=1.5)
    assert stop == pytest.approx(99.5)


def test_structural_model_is_identity_and_unknown_model_rejected():
    trigger = flat_candles(30)
    assert resolve_stop(SignalDirection.LONG, 100.0, 99.5, trigger) == 99.5
    with pytest.raises(ValueError):
        resolve_stop(SignalDirection.LONG, 100.0, 99.5, trigger, stop_model="percent")


# ── R-Drift regression through the REAL evaluate_signal -> sizing path ──

BIAS_ONLY = {"bias_sr": True, "fisher": False, "obv": False, "rsi": False, "ichimoku": False}


def _synthetic_bullish_bias():
    """Fixed BiasResult: support just below price (tight structural stop),
    resistance far above (target giving R:R >= 2 either stop model)."""
    return BiasResult(
        bias=Bias.BULLISH, swing=None,
        fib_levels={},  # keep fibs out of the target search — SR levels only
        sr_levels=[SRLevel(price=99.8, kind="support"),
                   SRLevel(price=140.0, kind="resistance")],
        reason="synthetic fixture",
    )


@pytest.fixture
def bullish_bias(monkeypatch):
    monkeypatch.setattr(signals_mod, "compute_bias", lambda candles: _synthetic_bullish_bias())


def test_rdrift_signal_stop_is_hybrid_and_rr_uses_it(bullish_bias):
    trigger = flat_candles(30, close=100.0, spread=2.0)   # ATR=2, close=100
    result = evaluate_signal(trigger, trigger, config=BIAS_ONLY,
                             stop_model="hybrid", atr_multiplier=1.5)
    assert isinstance(result, Signal)
    structural = 99.8 * (1 - signals_mod.STRUCTURAL_STOP_BUFFER)
    hybrid = 100.0 - 1.5 * 2.0                             # 97.0, wider than structural
    assert hybrid < structural
    assert result.stop == pytest.approx(hybrid)            # Signal carries the FINAL stop
    assert result.reward_risk == pytest.approx((140.0 - 100.0) / (100.0 - hybrid))


def test_rdrift_sizing_consumes_final_hybrid_distance(bullish_bias):
    """THE R-Drift regression: qty must come from the hybrid distance.
    Against pre-hybrid code (structural stop on the Signal), the same
    sizing call would produce a ~20x larger qty — this assertion fails."""
    trigger = flat_candles(30, close=100.0, spread=2.0)
    sig = evaluate_signal(trigger, trigger, config=BIAS_ONLY,
                          stop_model="hybrid", atr_multiplier=1.5)
    qty = compute_size(100_000.0, sig.entry, sig.stop, risk_pct=0.0075, sz_decimals=5)
    expected = (100_000.0 * 0.0075) / (100.0 - 97.0)       # risk_usd / FINAL distance
    assert qty == pytest.approx(expected, abs=1e-5)
    # sanity: sizing off the nominal structural distance would differ wildly
    structural = 99.8 * (1 - signals_mod.STRUCTURAL_STOP_BUFFER)
    wrong_qty = (100_000.0 * 0.0075) / (100.0 - structural)
    assert qty < wrong_qty / 5


def test_default_call_is_byte_identical_structural(bullish_bias):
    """Live engine passes no stop params — must remain the structural stop."""
    trigger = flat_candles(30, close=100.0, spread=2.0)
    sig = evaluate_signal(trigger, trigger, config=BIAS_ONLY)
    assert sig.stop == pytest.approx(99.8 * (1 - signals_mod.STRUCTURAL_STOP_BUFFER))
