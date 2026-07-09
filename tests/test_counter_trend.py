"""Track 2 counter-trend acceptance tests.

Two layers: (1) pure OBV/geometry helpers on hand values; (2) the E2E
detector via a mocked "passing" environment (Ichimoku cloud/TK, ATR,
swings, S/R, OBV gate) with one gate broken per test to prove each
blocks independently — the multi-gate confluence is the whole point."""
from __future__ import annotations

import pytest

import strategy.counter_trend as ct
from data.feed import Candle
from strategy.bias_4h import SRLevel, Swing, SwingDirection
from strategy.counter_trend import (
    CounterTrendSignal,
    _linreg_slope,
    _obv_divergence,
    _obv_lrs_flattening,
    evaluate_counter_trend,
    opposite_cloud_edge,
)


def candle(i, close, high=None, low=None, vol=100.0):
    return Candle(open_time_ms=i * 3600000, close_time_ms=(i + 1) * 3600000,
                  open=close, high=high if high is not None else close + 20,
                  low=low if low is not None else close - 20, close=close, volume=vol)


def series(closes):
    return [candle(i, c) for i, c in enumerate(closes)]


# ── pure helpers ──

def test_linreg_slope_known():
    assert _linreg_slope([0, 1, 2, 3, 4]) == pytest.approx(1.0)
    assert _linreg_slope([10, 8, 6, 4]) == pytest.approx(-2.0)
    assert _linreg_slope([5]) == 0.0


def test_obv_divergence_long_and_short():
    closes = [100.0] * 10 + [90.0]          # price fell over the window
    obv_up = [0.0] * 10 + [50.0]            # OBV rose -> bullish divergence
    obv_dn = [0.0] * 10 + [-50.0]
    assert _obv_divergence(obv_up, closes, lookback=10, is_long=True) is True
    assert _obv_divergence(obv_dn, closes, lookback=10, is_long=True) is False
    closes_up = [100.0] * 10 + [110.0]      # price rose
    assert _obv_divergence(obv_dn, closes_up, lookback=10, is_long=False) is True
    assert _obv_divergence(obv_up, closes_up, lookback=10, is_long=False) is False


def test_obv_lrs_flattening_detects_deceleration():
    steep_then_flat = list(range(0, 100, 10)) + [90] * 10   # prior slope steep, recent flat
    assert _obv_lrs_flattening(steep_then_flat, lookback=10) is True
    steady = list(range(0, 200, 10))                        # constant slope -> not flattening
    assert _obv_lrs_flattening(steady, lookback=10) is False


def test_opposite_cloud_edge(monkeypatch):
    monkeypatch.setattr(ct, "ichimoku_components", lambda c, variant="standard": (0, 0, 110.0, 100.0))
    assert opposite_cloud_edge(series([100] * 80), is_long=True) == 110.0
    assert opposite_cloud_edge(series([100] * 80), is_long=False) == 100.0


# ── detector: mocked passing environment, one gate broken per test ──

TRIG_LEN = 40


def install_long(monkeypatch, *, cur=(106.0, 104.0, 110.0, 100.0),
                 prev=(103.0, 104.0, 110.0, 100.0), atr=2.0, obv_pass=True,
                 support=101.0, swing_low=100.0):
    """Mock everything evaluate_counter_trend depends on into a state that
    yields a valid LONG unless a caller override breaks one gate."""
    def fake_components(candles, variant="standard"):
        return cur if len(candles) == TRIG_LEN else prev
    monkeypatch.setattr(ct, "ichimoku_components", fake_components)
    monkeypatch.setattr(ct, "wilder_atr", lambda c, period=14: [atr] * len(c))
    monkeypatch.setattr(ct, "on_balance_volume", lambda c: [0.0] * len(c))
    monkeypatch.setattr(ct, "_obv_confluence", lambda *a, **k: obv_pass)
    monkeypatch.setattr(ct, "detect_swings", lambda c, fractal_width=2: [
        Swing(start_price=120.0, end_price=swing_low, direction=SwingDirection.DOWN, end_index=5)])
    monkeypatch.setattr(ct, "horizontal_sr", lambda s, lookback=20: [
        SRLevel(price=support, kind="support")])


def long_candles(last_close=105.0, prev_close=95.0):
    closes = [100.0] * (TRIG_LEN - 2) + [prev_close, last_close]
    return series(closes)


def test_valid_long_fires_with_expected_geometry(monkeypatch):
    install_long(monkeypatch)
    sig = evaluate_counter_trend(series([100] * 200), long_candles(), fisher_value=-2.5)
    assert isinstance(sig, CounterTrendSignal)
    assert sig.direction == "LONG"
    assert sig.entry == 105.0
    assert sig.stop == pytest.approx(100.0 - 1.5 * 2.0)     # swing_low - mult*ATR = 97
    assert sig.target_at_entry == 110.0                     # upper cloud edge
    assert sig.reward_risk == pytest.approx((110.0 - 105.0) / (105.0 - 97.0))


def test_close_must_be_inside_kumo_wick_rejected(monkeypatch):
    install_long(monkeypatch)
    # candle pierced the cloud on the wick but CLOSED back above it (115 > cloud_top 110)
    sig = evaluate_counter_trend(series([100] * 200), long_candles(last_close=115.0),
                                 fisher_value=-2.5)
    assert sig is None


def test_fisher_gate_blocks(monkeypatch):
    install_long(monkeypatch)
    assert evaluate_counter_trend(series([100] * 200), long_candles(),
                                  fisher_value=-1.0) is None   # not extended enough


def test_obv_gate_blocks(monkeypatch):
    install_long(monkeypatch, obv_pass=False)
    assert evaluate_counter_trend(series([100] * 200), long_candles(),
                                  fisher_value=-2.5) is None


def test_requires_fresh_tk_cross(monkeypatch):
    # prior bar already had tenkan > kijun -> no fresh cross this bar
    install_long(monkeypatch, prev=(106.0, 104.0, 110.0, 100.0))
    assert evaluate_counter_trend(series([100] * 200), long_candles(),
                                  fisher_value=-2.5) is None


def test_requires_prior_close_below_cloud(monkeypatch):
    install_long(monkeypatch)
    # prev_close 105 is NOT below the prior cloud bottom (100) -> setup invalid
    assert evaluate_counter_trend(series([100] * 200), long_candles(prev_close=105.0),
                                  fisher_value=-2.5) is None


def test_support_proximity_required(monkeypatch):
    install_long(monkeypatch, support=80.0)    # 105-80=25 > 3*ATR(6) -> too far from support
    assert evaluate_counter_trend(series([100] * 200), long_candles(),
                                  fisher_value=-2.5) is None


def test_short_mirror_fires(monkeypatch):
    def fake_components(candles, variant="standard"):
        return (94.0, 96.0, 110.0, 100.0) if len(candles) == TRIG_LEN else (97.0, 96.0, 110.0, 100.0)
    monkeypatch.setattr(ct, "ichimoku_components", fake_components)
    monkeypatch.setattr(ct, "wilder_atr", lambda c, period=14: [2.0] * len(c))
    monkeypatch.setattr(ct, "on_balance_volume", lambda c: [0.0] * len(c))
    monkeypatch.setattr(ct, "_obv_confluence", lambda *a, **k: True)
    monkeypatch.setattr(ct, "detect_swings", lambda c, fractal_width=2: [
        Swing(start_price=90.0, end_price=110.0, direction=SwingDirection.UP, end_index=5)])
    monkeypatch.setattr(ct, "horizontal_sr", lambda s, lookback=20: [
        SRLevel(price=109.0, kind="resistance")])
    closes = [100.0] * (TRIG_LEN - 2) + [115.0, 105.0]      # prev above cloud, close back inside
    sig = evaluate_counter_trend(series([100] * 200), series(closes), fisher_value=2.5)
    assert isinstance(sig, CounterTrendSignal) and sig.direction == "SHORT"
    assert sig.stop == pytest.approx(110.0 + 1.5 * 2.0)     # swing_high + mult*ATR = 113
    assert sig.target_at_entry == 100.0                     # lower cloud edge


def test_unknown_obv_rule_rejected(monkeypatch):
    install_long(monkeypatch)
    with pytest.raises(ValueError):
        evaluate_counter_trend(series([100] * 200), long_candles(), fisher_value=-2.5,
                               obv_rule="moon_phase")
