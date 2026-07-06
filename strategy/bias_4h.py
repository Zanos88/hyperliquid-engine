"""4H structural bias: fractal swing detection, Fibonacci levels, S/R.

SCAFFOLD ONLY — implement per docs/STRATEGY_PSEUDOCODE.md and the cited
formulas in docs/RESEARCH_FINDINGS.md sections 3.2-3.4. Do not invent
parameter values not already fixed in config.yaml / the research doc.
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


def detect_swings(candles: Sequence[Candle], fractal_width: int = 2) -> list[Swing]:
    """Fractal-based swing detection (Williams fractal, width bars either side).

    TODO(Fable): implement. A candle is a confirmed swing high/low once
    `fractal_width` bars have closed after it (never repaints). See
    docs/STRATEGY_PSEUDOCODE.md "detect_swings".
    """
    raise NotImplementedError


def fibonacci_levels(swing: Swing) -> dict[str, float]:
    """TODO(Fable): retracement (FIB_RATIOS) + extension (FIB_EXTENSIONS) levels
    from `swing`. See docs/RESEARCH_FINDINGS.md 3.4 and pseudocode "fibonacci_levels".
    """
    raise NotImplementedError


def horizontal_sr(swings: Sequence[Swing], lookback: int = 20) -> list[SRLevel]:
    """TODO(Fable): derive support/resistance from prior swing highs/lows."""
    raise NotImplementedError


def compute_bias(candles: Sequence[Candle], fractal_width: int = 2, sr_lookback: int = 20) -> BiasResult:
    """Deterministic 4H bias per docs/STRATEGY_PSEUDOCODE.md "on 4H candle close".

    TODO(Fable): wire detect_swings -> fibonacci_levels -> horizontal_sr ->
    BULLISH/BEARISH/NEUTRAL decision exactly as specified in the pseudocode
    (0.618 retrace + nearest S/R holding). NEUTRAL = no trading.
    """
    raise NotImplementedError
