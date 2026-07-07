"""RSI confluence indicator (trigger layer).

Wilder's RSI (J. Welles Wilder, *New Concepts in Technical Trading
Systems*, 1978): 14-period default with Wilder smoothing. Confluence
rule per build spec: MIDLINE regime — RSI > 50 bullish / < 50 bearish
(crossover-style, consistent with Fisher/OBV usage; deliberately NOT the
70/30 overbought/oversold rule, which is a mean-reversion use case).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from data.feed import Candle

RSI_PERIOD = 14


class Vote(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


@dataclass(frozen=True)
class RsiReading:
    vote: Vote
    value: float | None  # None when insufficient history


def rsi_series(candles: Sequence[Candle], period: int = RSI_PERIOD) -> list[float | None]:
    """Wilder-smoothed RSI; None until `period` deltas exist."""
    n = len(candles)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out

    gains = losses = 0.0
    for i in range(1, period + 1):
        delta = candles[i].close - candles[i - 1].close
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period

    def to_rsi(g: float, l: float) -> float:
        if l == 0:
            return 100.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[period] = to_rsi(avg_gain, avg_loss)
    for i in range(period + 1, n):
        delta = candles[i].close - candles[i - 1].close
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
        out[i] = to_rsi(avg_gain, avg_loss)
    return out


def evaluate_rsi(candles: Sequence[Candle], period: int = RSI_PERIOD) -> RsiReading:
    """Vote from the last CLOSED candle: >50 LONG, <50 SHORT, ==50/no-data NONE."""
    series = rsi_series(candles, period=period)
    value = series[-1] if series else None
    if value is None:
        return RsiReading(Vote.NONE, None)
    if value > 50.0:
        return RsiReading(Vote.LONG, value)
    if value < 50.0:
        return RsiReading(Vote.SHORT, value)
    return RsiReading(Vote.NONE, value)
