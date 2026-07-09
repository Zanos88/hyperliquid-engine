"""Track 3 — 1D-bias + 4H-Fisher pullback-entry & exhaustion-cycling.

ISOLATED, BACKTEST-ONLY: no import from strategy/signals.py, never wired
into the live/dry-run engine. A multi-leg state machine (not discrete
R:R-gated bets), driven by the outcome simulator in backtest.py.

Thesis: inside a favorable 1D structural bias, a 4H Fisher extreme
AGAINST the immediate move is a pullback entry (buy the dip in a bullish
1D bias). Once in, an opposite Fisher extreme (exhaustion in the trade's
favor) FLIPS the leg to bank the pullback, cycling while the 1D bias
holds. Every leg carries its own ATR hard stop — the failure mode
(a trend pinning Fisher extended so the reset never comes) is capped by
the stop, not left open.

Stop semantics (user decision): a stop-out is the leg being invalidated,
NOT a reversal signal — so a stopped leg goes FLAT and the cycle re-arms
via the normal pullback-entry condition while the macro bias holds. Only
the Fisher EXHAUSTION extreme flips leg direction, never a stop.

Part 1 here is 1D bias access: compute_bias (strategy/bias_4h) is already
timeframe-agnostic (it consumes any candle sequence), so 1D bias needs no
new logic — just a no-lookahead daily slice at the current 4H timestamp.
"""
from __future__ import annotations

from typing import Sequence

from data.feed import Candle
from strategy.bias_4h import Bias, compute_bias


def daily_bias_at(daily_candles: Sequence[Candle], ts_ms: int,
                  fractal_width: int = 2, sr_lookback: int = 20) -> Bias:
    """1D structural bias using only daily candles CLOSED at/before ts_ms
    (the current 4H bar's close) — no lookahead. Reuses compute_bias
    unchanged; returns NEUTRAL when history is too thin for a swing.

    fractal_width/sr_lookback are compute_bias's own defaults, reused
    as-is (untuned for the daily timeframe — flagged in the build doc).
    """
    closed = [c for c in daily_candles if c.close_time_ms <= ts_ms]
    return compute_bias(closed, fractal_width=fractal_width, sr_lookback=sr_lookback).bias
