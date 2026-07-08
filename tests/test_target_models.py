"""V2.3 target-model acceptance tests: nearest_structure identity,
fib-extension preference (farther-of-two, bounded by intervening
structure), blue-sky ATR projection (only when NO opposing level
exists), default byte-identity, and R:R computed off the final target."""
from __future__ import annotations

import pytest

import strategy.signals as signals_mod
from strategy.bias_4h import Bias, BiasResult, SRLevel
from strategy.signals import (
    Signal,
    SignalDirection,
    evaluate_signal,
    resolve_target,
)
from tests.test_hybrid_stop import BIAS_ONLY, flat_candles

TRIGGER = flat_candles(30, close=100.0, spread=2.0)   # ATR = 2.0


def bias(fib_levels=None, sr_levels=None):
    return BiasResult(bias=Bias.BULLISH, swing=None,
                      fib_levels=fib_levels or {}, sr_levels=sr_levels or [],
                      reason="synthetic fixture")


# ── nearest_structure: identity with current behavior ──

def test_nearest_structure_is_current_behavior():
    b = bias(fib_levels={"0.618": 96.0, "1.272": 118.0},
             sr_levels=[SRLevel(105.0, "resistance"), SRLevel(95.0, "support")])
    t = resolve_target(SignalDirection.LONG, 100.0, b, TRIGGER)
    assert t == 105.0                       # nearest of {105 res, 118 ext} above entry
    t_short = resolve_target(SignalDirection.SHORT, 100.0, b, TRIGGER)
    assert t_short == 96.0                  # nearest below = 0.618 fib
    with pytest.raises(ValueError):
        resolve_target(SignalDirection.LONG, 100.0, b, TRIGGER, target_model="hopes")


# ── fib_extension_preferred ──

def test_extension_preferred_over_nearer_structure():
    b = bias(fib_levels={"1.272": 118.0, "1.618": 130.0},
             sr_levels=[SRLevel(105.0, "resistance")])
    t = resolve_target(SignalDirection.LONG, 100.0, b, TRIGGER,
                       target_model="fib_extension_preferred")
    assert t == 118.0                       # nearest extension BEYOND the 105 structure


def test_extension_bounded_by_intervening_structure():
    b = bias(fib_levels={"1.272": 118.0},
             sr_levels=[SRLevel(105.0, "resistance"), SRLevel(112.0, "resistance")])
    t = resolve_target(SignalDirection.LONG, 100.0, b, TRIGGER,
                       target_model="fib_extension_preferred")
    assert t == 112.0                       # capped at structure between nearest and ext


def test_extension_fallback_when_no_extension_beyond():
    b = bias(fib_levels={"1.272": 103.0},   # extension NEARER than the structure
             sr_levels=[SRLevel(105.0, "resistance")])
    t = resolve_target(SignalDirection.LONG, 100.0, b, TRIGGER,
                       target_model="fib_extension_preferred")
    assert t == 103.0                       # = nearest_structure result (ext IS the nearest)
    b2 = bias(sr_levels=[SRLevel(105.0, "resistance")])   # no extensions at all
    t2 = resolve_target(SignalDirection.LONG, 100.0, b2, TRIGGER,
                        target_model="fib_extension_preferred")
    assert t2 == 105.0


def test_extension_short_mirrored_with_bound():
    b = bias(fib_levels={"1.272": 82.0},
             sr_levels=[SRLevel(95.0, "support"), SRLevel(88.0, "support")])
    t = resolve_target(SignalDirection.SHORT, 100.0, b, TRIGGER,
                       target_model="fib_extension_preferred")
    assert t == 88.0                        # ext 82 beyond nearest 95, capped at 88 support
    b2 = bias(fib_levels={"1.272": 82.0}, sr_levels=[SRLevel(95.0, "support")])
    t2 = resolve_target(SignalDirection.SHORT, 100.0, b2, TRIGGER,
                        target_model="fib_extension_preferred")
    assert t2 == 82.0                       # no intervening support -> full extension


# ── blue_sky_atr ──

def test_blue_sky_fires_only_when_no_levels_exist():
    empty = bias()                          # nothing above or below
    t = resolve_target(SignalDirection.LONG, 100.0, empty, TRIGGER,
                       target_model="blue_sky_atr")
    assert t == pytest.approx(100.0 + 3.0 * 2.0)          # entry + mult*ATR
    t_short = resolve_target(SignalDirection.SHORT, 100.0, empty, TRIGGER,
                             target_model="blue_sky_atr")
    assert t_short == pytest.approx(100.0 - 3.0 * 2.0)

    # with a level present, behaves exactly like fib_extension_preferred
    b = bias(fib_levels={"1.272": 118.0}, sr_levels=[SRLevel(105.0, "resistance")])
    t2 = resolve_target(SignalDirection.LONG, 100.0, b, TRIGGER,
                        target_model="blue_sky_atr")
    assert t2 == 118.0


def test_blue_sky_no_bare_guess_without_atr_history():
    empty = bias()
    t = resolve_target(SignalDirection.LONG, 100.0, empty, flat_candles(10),
                       target_model="blue_sky_atr")    # ATR series all zero
    assert t is None
    # non-blue-sky models: no levels -> no target, unchanged
    assert resolve_target(SignalDirection.LONG, 100.0, empty, TRIGGER) is None
    assert resolve_target(SignalDirection.LONG, 100.0, empty, TRIGGER,
                          target_model="fib_extension_preferred") is None


# ── evaluate_signal wiring: default byte-identity + R:R off final target ──

def _rich_bias():
    """Support anchors the stop; resistance 110 is nearest target; 1.272
    extension at 140 lies beyond it."""
    return BiasResult(
        bias=Bias.BULLISH, swing=None,
        fib_levels={"1.272": 140.0},
        sr_levels=[SRLevel(price=99.8, kind="support"),
                   SRLevel(price=110.0, kind="resistance")],
        reason="synthetic fixture",
    )


@pytest.fixture
def rich_bias(monkeypatch):
    monkeypatch.setattr(signals_mod, "compute_bias", lambda candles: _rich_bias())


def test_default_call_target_unchanged(rich_bias):
    sig = evaluate_signal(TRIGGER, TRIGGER, config=BIAS_ONLY)
    assert isinstance(sig, Signal)
    assert sig.target == 110.0              # nearest structure, pre-V2.3 behavior


def test_signal_carries_extended_target_and_rr_uses_it(rich_bias):
    sig = evaluate_signal(TRIGGER, TRIGGER, config=BIAS_ONLY,
                          target_model="fib_extension_preferred")
    assert isinstance(sig, Signal)
    assert sig.target == 140.0              # extension preferred over 110 structure
    structural_stop = 99.8 * (1 - signals_mod.STRUCTURAL_STOP_BUFFER)
    assert sig.reward_risk == pytest.approx((140.0 - 100.0) / (100.0 - structural_stop))
