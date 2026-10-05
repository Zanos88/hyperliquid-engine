"""Unit coverage for strategy.signals.manual_entry_levels — the structural
stop/target proposals the Telegram trade panel and main.py surface for
MANUAL Buy/Sell entries.

This path was previously exercised only indirectly (via the engine); these
tests pin the pure math directly: nearest-support/resistance stops with the
shared STRUCTURAL_STOP_BUFFER, opposing-level targets pooled from fibs AND
S/R, and the None fallbacks when no structural level exists on the required
side. No live API, DB, or network — synthetic BiasResult fixtures only.
"""
from __future__ import annotations

import pytest

from strategy.bias_4h import Bias, BiasResult, SRLevel
from strategy.signals import STRUCTURAL_STOP_BUFFER, manual_entry_levels


def _bias(fib_levels=None, sr_levels=None):
    return BiasResult(bias=Bias.BULLISH, swing=None,
                      fib_levels=fib_levels or {}, sr_levels=sr_levels or [],
                      reason="synthetic fixture")


def test_levels_from_pooled_structure_both_directions():
    b = _bias(
        fib_levels={"0.618": 97.0, "1.272": 120.0},
        sr_levels=[
            SRLevel(95.0, "support"), SRLevel(90.0, "support"),
            SRLevel(105.0, "resistance"), SRLevel(110.0, "resistance"),
        ],
    )
    levels = manual_entry_levels(b, price=100.0)

    # Stops anchor on the NEAREST structural level, buffered away from it.
    assert levels["long_stop"] == pytest.approx(95.0 * (1 - STRUCTURAL_STOP_BUFFER))
    assert levels["short_stop"] == pytest.approx(105.0 * (1 + STRUCTURAL_STOP_BUFFER))

    # Targets are the nearest OPPOSING level, fibs and S/R pooled together.
    assert levels["long_target"] == 105.0   # min of {120 fib, 105/110 res} above 100
    assert levels["short_target"] == 97.0    # max of {97 fib, 95/90 sup} below 100


def test_fib_level_can_be_the_nearest_target():
    # A fib extension nearer than the nearest S/R must win the target slot.
    b = _bias(
        fib_levels={"0.618": 102.0},
        sr_levels=[SRLevel(95.0, "support"), SRLevel(108.0, "resistance")],
    )
    levels = manual_entry_levels(b, price=100.0)
    assert levels["long_target"] == 102.0    # fib 102 beats resistance 108


def test_none_when_no_structural_level_on_side():
    # No support below / no resistance above -> stops are None (manual entry
    # then falls back to the custom-stop path, per the docstring contract).
    b = _bias(sr_levels=[SRLevel(90.0, "support")])   # support only, below price
    levels = manual_entry_levels(b, price=100.0)
    assert levels["long_stop"] == pytest.approx(90.0 * (1 - STRUCTURAL_STOP_BUFFER))
    assert levels["short_stop"] is None       # no resistance above price
    assert levels["long_target"] is None       # no opposing level above price
    assert levels["short_target"] == 90.0      # nearest support below becomes the short target


def test_empty_bias_gives_all_none():
    levels = manual_entry_levels(_bias(), price=100.0)
    assert levels == {
        "long_stop": None, "long_target": None,
        "short_stop": None, "short_target": None,
    }
