"""Confluence logic: combines 4H bias + 1H trigger into a gated Signal.

SCAFFOLD ONLY — implement per docs/STRATEGY_PSEUDOCODE.md. Zero imports
from alerts/ or execution/ (build spec section 7) — a Signal is a plain
data object; delivery and (future) execution are consumers of it, not
producers. Do not violate this import boundary when implementing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Sequence

from data.feed import Candle
from strategy.bias_4h import BiasResult
from strategy.trigger_1h import TriggerResult

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


def evaluate_signal(
    candles_4h: Sequence[Candle],
    candles_1h: Sequence[Candle],
    now: datetime | None = None,
) -> Signal | SuppressedSignal | None:
    """Full confluence + exit + R:R gate, per docs/STRATEGY_PSEUDOCODE.md.

    TODO(Fable): implement the decision tree exactly as pseudocoded:
    1. compute_bias(candles_4h), evaluate_trigger(candles_1h)
    2. no trigger -> None; trigger against/without matching bias -> None (log only)
    3. stop = structural level beyond nearest S/R (+/- STRUCTURAL_STOP_BUFFER)
    4. target = next opposing 4H structural/Fib level
    5. R:R < MIN_REWARD_RISK -> SuppressedSignal (logged, no alert)
    6. else -> Signal

    Returns:
        Signal           - a valid, alertable entry
        SuppressedSignal - a trigger fired but was gated out (logged, no alert)
        None             - no trigger at all this bar
    """
    raise NotImplementedError
