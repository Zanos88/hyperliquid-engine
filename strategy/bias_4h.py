"""4H structural bias: fractal swing detection, Fibonacci levels, S/R.

Implements docs/STRATEGY_PSEUDOCODE.md "on 4H candle close" with the
cited sources in docs/RESEARCH_FINDINGS.md sections 3.2-3.4. Evaluates
closed candles only — swing points are confirmed only after
`fractal_width` bars close beyond them, so bias never repaints.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from data.feed import Candle

FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)
FIB_EXTENSIONS = (1.272, 1.618)


class Bias(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class SwingDirection(Enum):
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class Swing:
    start_price: float
    end_price: float
    direction: SwingDirection
    end_index: int


@dataclass(frozen=True)
class SRLevel:
    price: float
    kind: str  # "support" or "resistance"


@dataclass(frozen=True)
class BiasResult:
    bias: Bias
    swing: Swing | None
    fib_levels: dict[str, float]
    sr_levels: list[SRLevel]
    reason: str


def _is_fractal_high(candles: Sequence[Candle], i: int, width: int) -> bool:
    if i - width < 0 or i + width >= len(candles):
        return False
    window = candles[i - width : i + width + 1]
    return candles[i].high == max(c.high for c in window)


def _is_fractal_low(candles: Sequence[Candle], i: int, width: int) -> bool:
    if i - width < 0 or i + width >= len(candles):
        return False
    window = candles[i - width : i + width + 1]
    return candles[i].low == min(c.low for c in window)


def detect_swings(candles: Sequence[Candle], fractal_width: int = 2) -> list[Swing]:
    """Fractal-based swing detection (Williams fractal, width bars either side).

    A candle is confirmed as a swing point only once `fractal_width` bars
    have closed after it — the `i + width < len(candles)` bound in the
    fractal checks is what guarantees swings never repaint once formed.
    A Swing is each move between consecutive alternating swing points.
    """
    highs = [i for i in range(len(candles)) if _is_fractal_high(candles, i, fractal_width)]
    lows = [i for i in range(len(candles)) if _is_fractal_low(candles, i, fractal_width)]

    points = sorted(
        [(i, candles[i].high, "high") for i in highs] + [(i, candles[i].low, "low") for i in lows],
        key=lambda p: p[0],
    )

    swings: list[Swing] = []
    for j in range(1, len(points)):
        prev_i, prev_price, prev_kind = points[j - 1]
        cur_i, cur_price, cur_kind = points[j]
        if prev_kind == cur_kind:
            continue  # need alternating high/low to define a swing leg
        direction = SwingDirection.UP if cur_kind == "high" else SwingDirection.DOWN
        swings.append(
            Swing(start_price=prev_price, end_price=cur_price, direction=direction, end_index=cur_i)
        )
    return swings


def fibonacci_levels(swing: Swing) -> dict[str, float]:
    """Retracement levels back from the swing end, extensions beyond it."""
    span = swing.end_price - swing.start_price
    levels: dict[str, float] = {}
    for ratio in FIB_RATIOS:
        levels[f"{ratio}"] = swing.end_price - span * ratio
    for ratio in FIB_EXTENSIONS:
        levels[f"{ratio}"] = swing.end_price + span * (ratio - 1)
    return levels


def horizontal_sr(swings: Sequence[Swing], lookback: int = 20) -> list[SRLevel]:
    """Prior swing highs become resistance, swing lows become support."""
    recent = swings[-lookback:]
    levels: list[SRLevel] = []
    for s in recent:
        kind = "resistance" if s.direction == SwingDirection.UP else "support"
        levels.append(SRLevel(price=s.end_price, kind=kind))
    return levels


def _closest(levels: Sequence[SRLevel], price: float, kind: str) -> SRLevel | None:
    candidates = [lv for lv in levels if lv.kind == kind]
    if not candidates:
        return None
    return min(candidates, key=lambda lv: abs(lv.price - price))


def compute_bias(candles: Sequence[Candle], fractal_width: int = 2, sr_lookback: int = 20) -> BiasResult:
    """Deterministic 4H bias per docs/STRATEGY_PSEUDOCODE.md.

    Up-swing: price above the 0.618 retracement AND holding the nearest
    support -> BULLISH. Down-swing mirrored -> BEARISH. Everything else
    (including no confirmed swing yet) -> NEUTRAL = no trading.
    """
    swings = detect_swings(candles, fractal_width=fractal_width)
    if not swings:
        return BiasResult(Bias.NEUTRAL, None, {}, [], "no confirmed swing yet")

    last_swing = swings[-1]
    fib_levels = fibonacci_levels(last_swing)
    sr_levels = horizontal_sr(swings, lookback=sr_lookback)
    price = candles[-1].close

    if last_swing.direction == SwingDirection.UP:
        support = _closest(sr_levels, price, "support")
        if price > fib_levels["0.618"] and (support is None or price > support.price):
            return BiasResult(
                Bias.BULLISH, last_swing, fib_levels, sr_levels,
                f"price {price:.2f} above 0.618 retrace {fib_levels['0.618']:.2f} and holding support",
            )
        return BiasResult(Bias.NEUTRAL, last_swing, fib_levels, sr_levels, "below 0.618 retrace or lost support")

    resistance = _closest(sr_levels, price, "resistance")
    if price < fib_levels["0.618"] and (resistance is None or price < resistance.price):
        return BiasResult(
            Bias.BEARISH, last_swing, fib_levels, sr_levels,
            f"price {price:.2f} below 0.618 retrace {fib_levels['0.618']:.2f} and holding resistance",
        )
    return BiasResult(Bias.NEUTRAL, last_swing, fib_levels, sr_levels, "above 0.618 retrace or lost resistance")
