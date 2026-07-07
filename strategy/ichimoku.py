"""Ichimoku confluence indicator (bias layer).

Standard Hosoda parameters 9/26/52 (Tenkan/Kijun/Senkou B, displacement
26); crypto-adjusted 10/30/60 available as the configurable 'crypto'
variant (24/7 market, no weekend gaps — per build spec).

Confluence rule per build spec: price above the Kumo cloud AND
Tenkan > Kijun -> LONG; price below the cloud AND Tenkan < Kijun ->
SHORT; anything else (inside cloud, or cloud/TK disagreement) -> NONE.
Matches the bias-layer contextual pattern — not a standalone trigger.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from data.feed import Candle
from strategy.rsi import Vote

VARIANTS = {
    "standard": (9, 26, 52),
    "crypto": (10, 30, 60),
}


@dataclass(frozen=True)
class IchimokuReading:
    vote: Vote
    tenkan: float | None
    kijun: float | None
    senkou_a: float | None  # cloud edge A at the current bar (displaced)
    senkou_b: float | None  # cloud edge B at the current bar (displaced)
    variant: str = "standard"


def _midpoint(candles: Sequence[Candle], end: int, length: int) -> float | None:
    """(highest high + lowest low) / 2 over the `length` bars ending at `end` inclusive."""
    start = end - length + 1
    if start < 0:
        return None
    window = candles[start : end + 1]
    return (max(c.high for c in window) + min(c.low for c in window)) / 2


def evaluate_ichimoku(candles: Sequence[Candle], variant: str = "standard") -> IchimokuReading:
    """Evaluate on the last CLOSED candle.

    The cloud at the current bar is the Senkou span computed
    `displacement` bars ago and projected forward (standard construction:
    displacement = the Kijun length, 26 for standard / 30 for crypto).
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown ichimoku variant {variant!r} — allowed: {sorted(VARIANTS)}")
    tenkan_len, kijun_len, senkou_b_len = VARIANTS[variant]
    displacement = kijun_len

    last = len(candles) - 1
    cloud_origin = last - displacement
    if last < 0 or cloud_origin - senkou_b_len + 1 < 0:
        return IchimokuReading(Vote.NONE, None, None, None, None, variant)

    tenkan = _midpoint(candles, last, tenkan_len)
    kijun = _midpoint(candles, last, kijun_len)
    origin_tenkan = _midpoint(candles, cloud_origin, tenkan_len)
    origin_kijun = _midpoint(candles, cloud_origin, kijun_len)
    senkou_b = _midpoint(candles, cloud_origin, senkou_b_len)
    if None in (tenkan, kijun, origin_tenkan, origin_kijun, senkou_b):
        return IchimokuReading(Vote.NONE, tenkan, kijun, None, senkou_b, variant)
    senkou_a = (origin_tenkan + origin_kijun) / 2

    price = candles[last].close
    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)

    if price > cloud_top and tenkan > kijun:
        vote = Vote.LONG
    elif price < cloud_bottom and tenkan < kijun:
        vote = Vote.SHORT
    else:
        vote = Vote.NONE
    return IchimokuReading(vote, tenkan, kijun, senkou_a, senkou_b, variant)
