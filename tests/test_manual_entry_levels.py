"""Unit tests for strategy.signals.manual_entry_levels.

`manual_entry_levels` feeds the Telegram control-plane trade panel with
structural stop/target proposals for BOTH directions from the current 4H
bias state. main.py calls it every cycle a new trigger candle closes, but
it previously had no direct coverage — the panel's Buy/Sell levels rode
entirely on the indirect coverage of the private `_nearest_*` /
`_next_opposing_level_*` helpers.

These tests pin the four returned levels (long/short stop and target),
the structural-stop buffer, and the None fallbacks when no structural
level exists on the required side. `BiasResult` is built by hand so the
levels are deterministic and no candles/network are involved.
"""
from __future__ import annotations

import pytest

from strategy.bias_4h import Bias, BiasResult, SRLevel
from strategy.signals import STRUCTURAL_STOP_BUFFER, manual_entry_levels


def _bias(sr_levels, fib_levels) -> BiasResult:
    """Minimal BiasResult — manual_entry_levels reads only sr_levels/fib_levels."""
    return BiasResult(
        bias=Bias.NEUTRAL,
        swing=None,
        fib_levels=fib_levels,
        sr_levels=sr_levels,
        reason="synthetic",
    )


def test_levels_from_pooled_structure():
    # supports at 90/100, resistances at 120/130, plus fib levels either side.
    bias = _bias(
        sr_levels=[
            SRLevel(price=90.0, kind="support"),
            SRLevel(price=100.0, kind="support"),
            SRLevel(price=120.0, kind="resistance"),
            SRLevel(price=130.0, kind="resistance"),
        ],
        fib_levels={"0.618": 110.0, "1.272": 140.0},
    )
    levels = manual_entry_levels(bias, price=115.0)

    # long stop: nearest support BELOW price (100), buffered down 0.15%.
    assert levels["long_stop"] == pytest.approx(100.0 * (1 - STRUCTURAL_STOP_BUFFER))
    # long target: nearest opposing level ABOVE price — fibs+resistances pooled -> 120.
    assert levels["long_target"] == pytest.approx(120.0)
    # short stop: nearest resistance ABOVE price (120), buffered up 0.15%.
    assert levels["short_stop"] == pytest.approx(120.0 * (1 + STRUCTURAL_STOP_BUFFER))
    # short target: nearest opposing level BELOW price — fib 0.618 (110) beats support 100.
    assert levels["short_target"] == pytest.approx(110.0)


def test_none_when_no_structural_level_on_required_side():
    bias = _bias(
        sr_levels=[
            SRLevel(price=100.0, kind="support"),
            SRLevel(price=120.0, kind="resistance"),
        ],
        fib_levels={},
    )

    # price below every support -> no long stop anchor, and no level below
    # for a short target.
    below = manual_entry_levels(bias, price=80.0)
    assert below["long_stop"] is None
    assert below["short_target"] is None
    # a resistance still sits above 80 -> short stop / long target exist.
    assert below["short_stop"] == pytest.approx(120.0 * (1 + STRUCTURAL_STOP_BUFFER))
    assert below["long_target"] == pytest.approx(120.0)

    # price above every resistance -> no short stop anchor, no long target.
    above = manual_entry_levels(bias, price=140.0)
    assert above["short_stop"] is None
    assert above["long_target"] is None
    # a support still sits below 140 -> long stop / short target exist.
    assert above["long_stop"] == pytest.approx(100.0 * (1 - STRUCTURAL_STOP_BUFFER))
    assert above["short_target"] == pytest.approx(100.0)
