"""Confluence logic: combines 4H bias + 1H trigger into a gated Signal.

Zero imports from alerts/ or execution/ (build spec section 7) — a Signal
is a plain data object; delivery and (future) execution are consumers of
it, not producers. Implements docs/STRATEGY_PSEUDOCODE.md's entry/exit
decision tree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Sequence

from data.feed import Candle
from strategy.atr import wilder_atr
from strategy.bias_4h import Bias, BiasResult, compute_bias
from strategy.ichimoku import evaluate_ichimoku
from strategy.rsi import Vote, evaluate_rsi
from strategy.trigger_1h import TriggerDirection, TriggerResult, evaluate_trigger

MIN_REWARD_RISK = 2.0
STRUCTURAL_STOP_BUFFER = 0.0015  # 0.15% beyond the S/R/swing level
DEFAULT_ATR_MULTIPLIER = 1.5     # hybrid stop's ATR floor factor (sweep-tuned, not final)
STOP_MODELS = ("structural", "hybrid")

# All confluence indicators, independently toggleable. Defaults preserve
# the original 3-indicator behavior exactly (RSI/Ichimoku off until the
# user enables them via /settings -> Indicators).
INDICATOR_NAMES = ("bias_sr", "fisher", "obv", "rsi", "ichimoku")
DEFAULT_INDICATOR_CONFIG = {
    "bias_sr": True, "fisher": True, "obv": True, "rsi": False, "ichimoku": False,
}


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
    kind: str = "rr"  # "rr" | "fisher4h_exhaustion" — lets callers count suppression classes separately


def resolve_stop(
    direction: SignalDirection,
    entry_price: float,
    structural_stop: float,
    trigger_candles: Sequence[Candle],
    stop_model: str = "structural",
    atr_multiplier: float = DEFAULT_ATR_MULTIPLIER,
) -> float:
    """Final stop price under the configured stop model.

    "structural": the buffered S/R level unchanged (live default).
    "hybrid": the WIDER of structural vs an ATR floor — min() for longs,
    max() for shorts — so the stop clears trigger-TF noise (V2.2: the
    2026-07-08 backtest showed structural stops of 0.15-0.35% of price
    resolving inside a single trigger bar). Widens only, never tightens;
    falls back to structural when ATR history is insufficient (ATR==0).

    Sizing MUST consume the value returned here via Signal.stop — never
    the pre-hybrid structural level — or realized R drifts from nominal
    R (the R-Drift trap from the V2.2 research breakdown).
    """
    if stop_model not in STOP_MODELS:
        raise ValueError(f"unknown stop_model {stop_model!r} — allowed: {STOP_MODELS}")
    if stop_model == "structural":
        return structural_stop
    atr = wilder_atr(trigger_candles)[-1] if trigger_candles else 0.0
    if atr <= 0.0:
        return structural_stop
    if direction == SignalDirection.LONG:
        return min(structural_stop, entry_price - atr_multiplier * atr)
    return max(structural_stop, entry_price + atr_multiplier * atr)


def _next_opposing_level_above(bias_result: BiasResult, price: float) -> float | None:
    candidates = [lv for lv in bias_result.fib_levels.values() if lv > price]
    candidates += [lv.price for lv in bias_result.sr_levels if lv.kind == "resistance" and lv.price > price]
    return min(candidates) if candidates else None


def _next_opposing_level_below(bias_result: BiasResult, price: float) -> float | None:
    candidates = [lv for lv in bias_result.fib_levels.values() if lv < price]
    candidates += [lv.price for lv in bias_result.sr_levels if lv.kind == "support" and lv.price < price]
    return max(candidates) if candidates else None


def _nearest_support(bias_result: BiasResult, price: float) -> float | None:
    supports = [lv.price for lv in bias_result.sr_levels if lv.kind == "support"]
    return max((p for p in supports if p < price), default=None)


def _nearest_resistance(bias_result: BiasResult, price: float) -> float | None:
    resistances = [lv.price for lv in bias_result.sr_levels if lv.kind == "resistance"]
    return min((p for p in resistances if p > price), default=None)


def manual_entry_levels(bias_result: BiasResult, price: float) -> dict:
    """Structural stop/target proposals for MANUAL entries in both
    directions, from the current bias state — consumed by the control
    plane's trade panel (strategy-anchored Buy/Sell). Values are None when
    no structural level exists on the required side; manual entries then
    fall back to the custom-stop path. Same levels/buffer as the
    automated path — no separate logic."""
    support = _nearest_support(bias_result, price)
    resistance = _nearest_resistance(bias_result, price)
    return {
        "long_stop": support * (1 - STRUCTURAL_STOP_BUFFER) if support is not None else None,
        "long_target": _next_opposing_level_above(bias_result, price),
        "short_stop": resistance * (1 + STRUCTURAL_STOP_BUFFER) if resistance is not None else None,
        "short_target": _next_opposing_level_below(bias_result, price),
    }


def evaluate_confluence(
    candles_bias: Sequence[Candle],
    candles_trigger: Sequence[Candle],
    config: dict | None = None,
    ichimoku_variant: str = "standard",
) -> tuple[SignalDirection | None, dict, BiasResult]:
    """Dynamic confluence: entry direction requires ALL ENABLED indicators
    to agree. Disabling an indicator removes it from the requirement.

    One gate function, no per-indicator duplication: every indicator
    contributes a Vote; alignment is computed over the enabled subset.
    Fisher's vote exists only on its cross bar, which makes the default
    config (bias+fisher+obv) behave exactly like the original 3-indicator
    logic. Returns (direction|None, per-indicator readings, bias_result).
    bias_result is always computed — structural stops/targets and
    market_state need it even when its vote is disabled.
    """
    cfg = {**DEFAULT_INDICATOR_CONFIG, **(config or {})}

    bias_result = compute_bias(candles_bias)
    trigger_result: TriggerResult = evaluate_trigger(candles_trigger)
    rsi_reading = evaluate_rsi(candles_trigger)
    ichi = evaluate_ichimoku(candles_bias, variant=ichimoku_variant)

    bias_vote = ("LONG" if bias_result.bias == Bias.BULLISH
                 else "SHORT" if bias_result.bias == Bias.BEARISH else "NONE")
    fisher_vote = ("LONG" if trigger_result.fisher_cross == "bullish"
                   else "SHORT" if trigger_result.fisher_cross == "bearish" else "NONE")
    obv_vote = ("LONG" if trigger_result.obv_confirmation == "rising"
                else "SHORT" if trigger_result.obv_confirmation == "falling" else "NONE")

    readings = {
        "bias_sr": {"enabled": cfg["bias_sr"], "vote": bias_vote,
                    "bias": bias_result.bias.value, "reason": bias_result.reason},
        "fisher": {"enabled": cfg["fisher"], "vote": fisher_vote,
                   "cross": trigger_result.fisher_cross, "value": trigger_result.fisher_value},
        "obv": {"enabled": cfg["obv"], "vote": obv_vote,
                "state": trigger_result.obv_confirmation, "value": trigger_result.obv_value},
        "rsi": {"enabled": cfg["rsi"], "vote": rsi_reading.vote.value, "value": rsi_reading.value},
        "ichimoku": {"enabled": cfg["ichimoku"], "vote": ichi.vote.value,
                     "tenkan": ichi.tenkan, "kijun": ichi.kijun,
                     "senkou_a": ichi.senkou_a, "senkou_b": ichi.senkou_b,
                     "variant": ichi.variant},
    }

    enabled_votes = [r["vote"] for name, r in readings.items() if cfg[name]]
    if not enabled_votes:
        return None, readings, bias_result  # nothing enabled -> never signal
    if all(v == "LONG" for v in enabled_votes):
        return SignalDirection.LONG, readings, bias_result
    if all(v == "SHORT" for v in enabled_votes):
        return SignalDirection.SHORT, readings, bias_result
    return None, readings, bias_result


def evaluate_signal(
    candles_4h: Sequence[Candle],
    candles_1h: Sequence[Candle],
    now: datetime | None = None,
    config: dict | None = None,
    ichimoku_variant: str = "standard",
    return_readings: bool = False,
    stop_model: str = "structural",
    atr_multiplier: float = DEFAULT_ATR_MULTIPLIER,
):
    """Full confluence + exit + R:R gate.

    Returns Signal | SuppressedSignal | None (default), or a
    (result, readings) tuple when return_readings=True — readings are the
    per-indicator snapshot destined for indicators_snapshot JSONB.

    stop_model/atr_multiplier select the stop construction (see
    resolve_stop). Defaults preserve the pre-V2.2 structural-only
    behavior exactly — the live engine passes nothing here until the
    sweep results are reviewed (user decision 2026-07-08).
    """
    direction, readings, bias_result = evaluate_confluence(
        candles_4h, candles_1h, config=config, ichimoku_variant=ichimoku_variant,
    )

    def _ret(result):
        return (result, readings) if return_readings else result

    if direction is None:
        return _ret(None)

    # Entry decision on close; entry price is that same close — no
    # intra-candle fill assumption (build spec section 11).
    entry_price = candles_1h[-1].close

    if direction == SignalDirection.LONG:
        support = _nearest_support(bias_result, entry_price)
        if support is None:
            return _ret(None)  # no structural level to anchor a stop — never a bare-percentage stop
        structural_stop = support * (1 - STRUCTURAL_STOP_BUFFER)
        target = _next_opposing_level_above(bias_result, entry_price)
    else:
        resistance = _nearest_resistance(bias_result, entry_price)
        if resistance is None:
            return _ret(None)
        structural_stop = resistance * (1 + STRUCTURAL_STOP_BUFFER)
        target = _next_opposing_level_below(bias_result, entry_price)

    if target is None:
        return _ret(None)  # no opposing structural level to target

    # R:R, the Signal, and (downstream) sizing all use the FINAL resolved
    # stop — a hybrid widening must flow through everything or realized R
    # silently drifts from nominal R.
    stop = resolve_stop(direction, entry_price, structural_stop, candles_1h,
                        stop_model=stop_model, atr_multiplier=atr_multiplier)

    risk = abs(entry_price - stop)
    reward = abs(target - entry_price)
    if risk == 0:
        return _ret(None)
    rr = reward / risk

    if rr < MIN_REWARD_RISK:
        return _ret(SuppressedSignal(direction, rr, f"R:R {rr:.2f} below minimum {MIN_REWARD_RISK}"))

    active = [f"{name}:{r['vote']}" for name, r in readings.items() if r["enabled"]]
    return _ret(Signal(
        direction=direction,
        entry=entry_price,
        stop=stop,
        target=target,
        reward_risk=rr,
        timestamp=now or datetime.now(timezone.utc),
        bias_reason=bias_result.reason,
        trigger_reason="confluence: " + " + ".join(active),
    ))
