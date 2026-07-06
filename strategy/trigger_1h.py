"""1H entry trigger: Fisher Transform + OBV confirmation.

Formulas and parameter choices cited in docs/RESEARCH_FINDINGS.md
sections 3.2 and 3.3. Evaluated only on closed 1H candles (caller must
never pass an in-progress candle — see data/feed.py fetch_candles).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from data.feed import Candle

FISHER_PERIOD = 9          # Ehlers' original default, cited in RESEARCH_FINDINGS 3.2
OBV_SMA_PERIOD = 20         # this repo's default; flagged as an assumption in 3.3


def fisher_transform(candles: Sequence[Candle], period: int = FISHER_PERIOD) -> tuple[list[float], list[float]]:
    """Returns (fisher_line, trigger_line) where trigger_line[i] = fisher_line[i-1].

    Implements Ehlers' construction:
        x = clamp(2 * ((price - min(period)) / (max(period) - min(period)) - 0.5))
        x = 0.33 * 2 * x + 0.67 * x_prev   (smoothing)
        fisher[t] = 0.5 * ln((1+x)/(1-x)) + 0.5 * fisher[t-1]
    """
    n = len(candles)
    fisher = [0.0] * n
    x_prev = 0.0
    fisher_prev = 0.0

    for i in range(n):
        if i < period - 1:
            fisher[i] = 0.0
            continue
        window = candles[i - period + 1 : i + 1]
        hi = max(c.high for c in window)
        lo = min(c.low for c in window)
        mid = (candles[i].high + candles[i].low) / 2
        raw = 0.0 if hi == lo else 2 * ((mid - lo) / (hi - lo) - 0.5)
        x = 0.33 * 2 * raw + 0.67 * x_prev
        x = max(min(x, 0.999), -0.999)
        f = 0.5 * math.log((1 + x) / (1 - x)) + 0.5 * fisher_prev
        fisher[i] = f
        x_prev = x
        fisher_prev = f

    trigger = [0.0] + fisher[:-1]
    return fisher, trigger


def on_balance_volume(candles: Sequence[Candle]) -> list[float]:
    """Standard OBV, cited in RESEARCH_FINDINGS 3.3."""
    obv = [0.0] * len(candles)
    for i in range(1, len(candles)):
        if candles[i].close > candles[i - 1].close:
            obv[i] = obv[i - 1] + candles[i].volume
        elif candles[i].close < candles[i - 1].close:
            obv[i] = obv[i - 1] - candles[i].volume
        else:
            obv[i] = obv[i - 1]
    return obv


def sma(values: Sequence[float], period: int) -> list[float]:
    out = [0.0] * len(values)
    for i in range(len(values)):
        if i < period - 1:
            out[i] = values[i]
            continue
        out[i] = sum(values[i - period + 1 : i + 1]) / period
    return out


class TriggerDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


@dataclass(frozen=True)
class TriggerResult:
    direction: TriggerDirection
    fisher_cross: str  # "bullish", "bearish", or "none"
    obv_confirmation: str  # "rising", "falling", or "none"
    fisher_value: float
    obv_value: float


def evaluate_trigger(
    candles: Sequence[Candle],
    fisher_period: int = FISHER_PERIOD,
    obv_sma_period: int = OBV_SMA_PERIOD,
) -> TriggerResult:
    """Evaluate the 1H trigger on the last CLOSED candle only.

    `candles` must contain only closed candles, most recent last.
    """
    if len(candles) < max(fisher_period, obv_sma_period) + 2:
        return TriggerResult(TriggerDirection.NONE, "none", "none", 0.0, 0.0)

    fisher, trigger = fisher_transform(candles, period=fisher_period)
    obv = on_balance_volume(candles)
    obv_avg = sma(obv, period=obv_sma_period)

    bullish_cross = fisher[-2] <= trigger[-2] and fisher[-1] > trigger[-1]
    bearish_cross = fisher[-2] >= trigger[-2] and fisher[-1] < trigger[-1]

    obv_rising = obv[-1] > obv_avg[-1] and obv[-1] > obv[-2]
    obv_falling = obv[-1] < obv_avg[-1] and obv[-1] < obv[-2]

    cross_label = "bullish" if bullish_cross else "bearish" if bearish_cross else "none"
    obv_label = "rising" if obv_rising else "falling" if obv_falling else "none"

    if bullish_cross and obv_rising:
        direction = TriggerDirection.LONG
    elif bearish_cross and obv_falling:
        direction = TriggerDirection.SHORT
    else:
        direction = TriggerDirection.NONE

    return TriggerResult(direction, cross_label, obv_label, fisher[-1], obv[-1])
