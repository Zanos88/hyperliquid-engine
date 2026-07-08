"""Wilder's Average True Range — volatility floor for the hybrid stop.

Standard construction (Wilder 1978; adopted per the V2.2 research
breakdown in docs/V2_2_STOP_SWEEP_FISHER4H.md — the formula itself is
uncontroversial):

    TR_i  = max(high_i - low_i, |high_i - prev_close|, |low_i - prev_close|)
    ATR_p = mean(TR_1 .. TR_p)                     (seed)
    ATR_i = (ATR_{i-1} * (p - 1) + TR_i) / p       (Wilder smoothing)

Causal — bar i uses only bars <= i — so a precomputed series is
lookahead-safe for walk-forward replay.
"""
from __future__ import annotations

from typing import Sequence

from data.feed import Candle

ATR_PERIOD = 14  # generic convention, not tuned; the sweep is the tuning pass


def wilder_atr(candles: Sequence[Candle], period: int = ATR_PERIOD) -> list[float]:
    """Full ATR series aligned to `candles`.

    Entries before the seed window (index < period) are 0.0 — callers
    must treat 0.0 as "insufficient history", never as a real range
    (the hybrid stop falls back to structural-only in that case).
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    n = len(candles)
    out = [0.0] * n
    if n < period + 1:
        return out

    true_ranges = [0.0] * n
    for i in range(1, n):
        h, lo, prev_close = candles[i].high, candles[i].low, candles[i - 1].close
        true_ranges[i] = max(h - lo, abs(h - prev_close), abs(lo - prev_close))

    atr = sum(true_ranges[1 : period + 1]) / period
    out[period] = atr
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + true_ranges[i]) / period
        out[i] = atr
    return out
