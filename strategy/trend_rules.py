"""Causal long/flat trend position rules (rounds 3-4 tournament family).

Shared by the dry-run forward test (forward_test.py) and the research
scripts. Each function returns a 0/1 position series aligned to `candles`
(newest last): pos[i] is the position DECIDED at the close of bar i, which
per the marking convention earns bar i+1's return. Fully causal — bar i's
decision uses only bars <= i.
"""
from __future__ import annotations

from typing import Sequence

from data.feed import Candle


def sma_positions(candles: Sequence[Candle], period: int) -> list[int]:
    """Long while close > SMA(period), else flat. 0 during warm-up."""
    closes = [c.close for c in candles]
    pos = [0] * len(closes)
    running = 0.0
    for i, px in enumerate(closes):
        running += px
        if i >= period:
            running -= closes[i - period]
        if i >= period - 1:
            pos[i] = 1 if px > running / period else 0
    return pos


def tsmom_positions(candles: Sequence[Candle], lookback: int) -> list[int]:
    """Long while close > close `lookback` bars ago, else flat."""
    closes = [c.close for c in candles]
    return [1 if i >= lookback and closes[i] > closes[i - lookback] else 0
            for i in range(len(closes))]
