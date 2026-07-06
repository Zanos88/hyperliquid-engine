"""Confluence logic: combines 4H bias + 1H trigger into a gated Signal.

Zero imports from alerts/ or execution/ (see build spec section 7) —
a Signal is a plain data object; delivery and (future) execution are
consumers of it, not producers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Sequence

from data.feed import Candle
from strategy.bias_4h import Bias, BiasResult, compute_bias
from strategy.trigger_1h import TriggerDirection, TriggerResult, evaluate_trigger

MIN_REWARD_RISK = 2.0
STRUCTURAL_STOP_BUFFER = 0.0015  # 0.15% beyond the S/R/swing level


class SignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class Signal:
    direction: SignalDirection
    entry: float
    stop: float
    target: float
    reward_risk: float
    timestamp: datetime
    bias_reason: str
    trigger_reason: str


@dataclass(frozen=True)
class SuppressedSignal:
    direction: SignalDirection
    reward_risk: float
    reason: str


def _next_opposing_level_above(bias_result: BiasResult, price: float) -> float | None:
    candidates = [lv for lv in bias_result.fib_levels.values() if lv > price]
    candidates += [lv.price for lv in bias_result.sr_levels if lv.kind == "resistance" and lv.price > price]
    return min(candidates) if candidates else None


def _next_opposing_level_below(bias_result: BiasResult, price: float) -> float | None:
    candidates = [lv for lv in bias_result.fib_levels.values() if lv < price]
    candidates += [lv.price for lv in bias_result.sr_levels if lv.kind == "support" and lv.price < price]
    return max(candidates) if candidates else None


def _nearest_support(bias_result: BiasResult, price: float) -> float | None:
    supports = [lv.price for lv in bias_result.sr_levels if lv.kind == "support"]
    return max((p for p in supports if p < price), default=None)


def _nearest_resistance(bias_result: BiasResult, price: float) -> float | None:
    resistances = [lv.price for lv in bias_result.sr_levels if lv.kind == "resistance"]
    return min((p for p in resistances if p > price), default=None)


def evaluate_signal(
    candles_4h: Sequence[Candle],
    candles_1h: Sequence[Candle],
    now: datetime | None = None,
) -> Signal | SuppressedSignal | None:
    """Full confluence + exit + R:R gate, per docs/STRATEGY_PSEUDOCODE.md.

    Returns:
        Signal          - a valid, alertable entry
        SuppressedSignal - a trigger fired but was gated out (logged, no alert)
        None            - no trigger at all this bar
    """
    bias_result = compute_bias(candles_4h)
    trigger_result: TriggerResult = evaluate_trigger(candles_1h)

    if trigger_result.direction == TriggerDirection.NONE:
        return None

    if trigger_result.direction == TriggerDirection.LONG and bias_result.bias != Bias.BULLISH:
        return None  # 1H trigger against/without 4H bias: logged by caller, no signal object
    if trigger_result.direction == TriggerDirection.SHORT and bias_result.bias != Bias.BEARISH:
        return None

    entry_price = candles_1h[-1].close
    direction = SignalDirection.LONG if trigger_result.direction == TriggerDirection.LONG else SignalDirection.SHORT

    if direction == SignalDirection.LONG:
        support = _nearest_support(bias_result, entry_price)
        if support is None:
            return None
        stop = support * (1 - STRUCTURAL_STOP_BUFFER)
        target = _next_opposing_level_above(bias_result, entry_price)
    else:
        resistance = _nearest_resistance(bias_result, entry_price)
        if resistance is None:
            return None
        stop = resistance * (1 + STRUCTURAL_STOP_BUFFER)
        target = _next_opposing_level_below(bias_result, entry_price)

    if target is None:
        return None

    risk = abs(entry_price - stop)
    reward = abs(target - entry_price)
    if risk == 0:
        return None
    rr = reward / risk

    if rr < MIN_REWARD_RISK:
        return SuppressedSignal(direction, rr, f"R:R {rr:.2f} below minimum {MIN_REWARD_RISK}")

    return Signal(
        direction=direction,
        entry=entry_price,
        stop=stop,
        target=target,
        reward_risk=rr,
        timestamp=now or datetime.now(timezone.utc),
        bias_reason=bias_result.reason,
        trigger_reason=f"Fisher {trigger_result.fisher_cross} cross + OBV {trigger_result.obv_confirmation}",
    )
