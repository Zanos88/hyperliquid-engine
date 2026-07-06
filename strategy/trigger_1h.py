"""1H entry trigger: Fisher Transform + OBV confirmation.

SCAFFOLD ONLY — implement per docs/RESEARCH_FINDINGS.md sections 3.2/3.3
(cited formulas + chosen parameters) and docs/STRATEGY_PSEUDOCODE.md
"on 1H candle close". Must evaluate on closed candles only — never pass or
assume an in-progress candle.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from data.feed import Candle

FISHER_PERIOD = 10         # Ehlers' primary-source default (Rev. 2), cited in RESEARCH_FINDINGS 3.2
OBV_SMA_PERIOD = 20         # this repo's default; flagged as an assumption in 3.3


def fisher_transform(candles: Sequence[Candle], period: int = FISHER_PERIOD) -> tuple[list[float], list[float]]:
    """Returns (fisher_line, trigger_line) where trigger_line[i] = fisher_line[i-1].

    TODO(Fable): implement Ehlers' construction exactly as documented in
    docs/RESEARCH_FINDINGS.md 3.2:
        x = clamp(2 * ((price - min(period)) / (max(period) - min(period)) - 0.5))
        x = 0.33 * 2 * x + 0.67 * x_prev
        fisher[t] = 0.5 * ln((1+x)/(1-x)) + 0.5 * fisher[t-1]
    """
    raise NotImplementedError


def on_balance_volume(candles: Sequence[Candle]) -> list[float]:
    """Standard OBV, cited in RESEARCH_FINDINGS 3.3. TODO(Fable): implement."""
    raise NotImplementedError


def sma(values: Sequence[float], period: int) -> list[float]:
    """TODO(Fable): simple moving average, used for the OBV confirmation rule."""
    raise NotImplementedError


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

    TODO(Fable): implement per docs/RESEARCH_FINDINGS.md 3.2/3.3:
    - bullish cross: fisher[-2] <= trigger[-2] and fisher[-1] > trigger[-1]
    - bearish cross: fisher[-2] >= trigger[-2] and fisher[-1] < trigger[-1]
    - OBV rising: obv[-1] > obv_sma[-1] and obv[-1] > obv[-2] (mirror for falling)
    `candles` must contain only closed candles, most recent last.
    """
    raise NotImplementedError
