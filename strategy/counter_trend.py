"""E2E Ichimoku counter-trend (mean-reversion) signal — Track 2.

ISOLATED from the trend system: this module does NOT import from or
modify strategy/signals.py. It is a second, independent signal path,
BACKTEST-ONLY — never wired into the live/dry-run engine.

Setup (long; short mirrored): price has been BELOW the Kumo and is
pressing into a structural support; Tenkan crosses above Kijun (TK
cross) and the candle CLOSES back inside the cloud (wick-only
penetration is rejected as noise). Two confluence gates then confirm a
likely exhaustion/reversal: a Fisher extreme (|Fisher| >= threshold, on
a caller-chosen timeframe so fisher_tf stays a sweep axis) and an OBV
signal (regular divergence, or the swept LRS-flattening variant). Stop
is an ATR offset beyond the nearest fractal swing, fixed at entry;
target is the OPPOSITE cloud edge — dynamic, recomputed each bar by the
backtest outcome simulator (target_at_entry here is just the entry-bar
snapshot for logging/R:R).

All detection is deterministic numeric/boolean over CLOSED candles.
Structure (S/R + fractal swings) is read from the bias candles; the
Ichimoku pattern, OBV, and ATR are read from the trigger candles —
matching the 4h-bias / 1h-trigger split of the live system.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from data.feed import Candle
from strategy.atr import wilder_atr
from strategy.bias_4h import SwingDirection, detect_swings, horizontal_sr
from strategy.ichimoku import ichimoku_components
from strategy.trigger_1h import on_balance_volume

DEFAULT_EXHAUSTION_THRESHOLD = 2.0
DEFAULT_ATR_MULTIPLIER = 1.5
DEFAULT_OBV_LOOKBACK = 14
DEFAULT_SUPPORT_PROXIMITY_ATR = 3.0   # entry must be within N*ATR of the reversal level
DEFAULT_CROSS_LOOKBACK = 6            # TK cross must have printed within this many bars ("precedes")
OBV_RULES = ("divergence", "lrs_flattening")


@dataclass(frozen=True)
class CounterTrendSignal:
    direction: str          # "LONG" | "SHORT"
    entry: float
    stop: float             # fixed ATR offset beyond the nearest fractal swing
    target_at_entry: float  # opposite cloud edge at the entry bar (sim recomputes each bar)
    reward_risk: float
    fisher_value: float
    obv_rule: str
    reason: str


# ── OBV confluence rules (swept: divergence primary, lrs_flattening secondary) ──

def _linreg_slope(values: Sequence[float]) -> float:
    """Ordinary least-squares slope over evenly-spaced samples."""
    n = len(values)
    if n < 2:
        return 0.0
    xbar = (n - 1) / 2.0
    ybar = sum(values) / n
    num = sum((i - xbar) * (v - ybar) for i, v in enumerate(values))
    den = sum((i - xbar) ** 2 for i in range(n))
    return num / den if den else 0.0


def _obv_divergence(obv: Sequence[float], closes: Sequence[float],
                    lookback: int, is_long: bool) -> bool:
    """Regular divergence (locked rule #3): price and OBV disagree over
    the window. Long -> price lower but OBV higher (bullish); short ->
    price higher but OBV lower (bearish)."""
    if len(obv) <= lookback or len(closes) <= lookback:
        return False
    price_delta = closes[-1] - closes[-1 - lookback]
    obv_delta = obv[-1] - obv[-1 - lookback]
    if is_long:
        return price_delta < 0 and obv_delta > 0
    return price_delta > 0 and obv_delta < 0


def _obv_lrs_flattening(obv: Sequence[float], lookback: int) -> bool:
    """Volume-momentum flattening: OBV's linear-regression slope over the
    most recent half-window is smaller in magnitude than over the prior
    half — momentum decelerating, i.e. the move is losing conviction.
    Direction-agnostic confluence for a reversal."""
    if len(obv) < 2 * lookback:
        return False
    recent = obv[-lookback:]
    prior = obv[-2 * lookback:-lookback]
    return abs(_linreg_slope(recent)) < abs(_linreg_slope(prior))


def _obv_confluence(obv, closes, lookback, is_long, obv_rule) -> bool:
    if obv_rule == "divergence":
        return _obv_divergence(obv, closes, lookback, is_long)
    if obv_rule == "lrs_flattening":
        return _obv_lrs_flattening(obv, lookback)
    raise ValueError(f"unknown obv_rule {obv_rule!r} — allowed: {OBV_RULES}")


# ── structural anchors (from the bias candles) ──

def _nearest_swing_low_below(swings, price: float) -> float | None:
    lows = [s.end_price for s in swings if s.direction == SwingDirection.DOWN]
    return max((p for p in lows if p < price), default=None)


def _nearest_swing_high_above(swings, price: float) -> float | None:
    highs = [s.end_price for s in swings if s.direction == SwingDirection.UP]
    return min((p for p in highs if p > price), default=None)


def _nearest_support_below(sr_levels, price: float) -> float | None:
    supports = [lv.price for lv in sr_levels if lv.kind == "support" and lv.price <= price]
    return max(supports, default=None)


def _nearest_resistance_above(sr_levels, price: float) -> float | None:
    resistances = [lv.price for lv in sr_levels if lv.kind == "resistance" and lv.price >= price]
    return min(resistances, default=None)


def opposite_cloud_edge(candles_trigger: Sequence[Candle], is_long: bool,
                        variant: str = "standard") -> float | None:
    """Dynamic target: upper cloud edge for a long, lower edge for a
    short. Recomputed each bar by the outcome simulator as the Senkou
    spans move. None when the cloud is undefined."""
    _, _, cloud_top, cloud_bottom = ichimoku_components(candles_trigger, variant=variant)
    if cloud_top is None or cloud_bottom is None:
        return None
    return cloud_top if is_long else cloud_bottom


def evaluate_counter_trend(
    candles_bias: Sequence[Candle],
    candles_trigger: Sequence[Candle],
    fisher_recent_min: float,
    fisher_recent_max: float,
    variant: str = "standard",
    exhaustion_threshold: float = DEFAULT_EXHAUSTION_THRESHOLD,
    obv_rule: str = "divergence",
    atr_multiplier: float = DEFAULT_ATR_MULTIPLIER,
    obv_lookback: int = DEFAULT_OBV_LOOKBACK,
    support_proximity_atr: float = DEFAULT_SUPPORT_PROXIMITY_ATR,
    cross_lookback: int = DEFAULT_CROSS_LOOKBACK,
    fractal_width: int = 2,
    sr_lookback: int = 20,
) -> CounterTrendSignal | None:
    """Return a CounterTrendSignal or None.

    Both the TK cross AND the Fisher exhaustion PRECEDE the entry — that
    is the whole mean-reversion thesis. The down-move exhausts (Fisher
    hits its extreme at the low), THEN price reverses and reclaims the
    cloud (the entry). So the caller supplies the recent-window extremes
    of Fisher on the chosen fisher_tf (sweep axis) — fisher_recent_min /
    fisher_recent_max over the setup window — not the entry-bar value.
    (Gating on the entry-bar Fisher fired on 0 bars: by the time price
    closes back inside the Kumo the oversold extreme has already passed.)
    Likewise the TK cross must have printed within the last
    `cross_lookback` bars while price was on the far side of the cloud;
    the entry confirms on the current candle closing INSIDE the Kumo."""
    if obv_rule not in OBV_RULES:
        raise ValueError(f"unknown obv_rule {obv_rule!r} — allowed: {OBV_RULES}")
    if len(candles_trigger) <= cross_lookback:
        return None

    tenkan, kijun, cloud_top, cloud_bottom = ichimoku_components(candles_trigger, variant=variant)
    past = candles_trigger[:-cross_lookback]
    p_tenkan, p_kijun, p_cloud_top, p_cloud_bottom = ichimoku_components(past, variant=variant)
    if None in (tenkan, kijun, cloud_top, cloud_bottom,
                p_tenkan, p_kijun, p_cloud_top, p_cloud_bottom):
        return None

    atr = wilder_atr(candles_trigger)[-1] if candles_trigger else 0.0
    if atr <= 0.0:
        return None

    close = candles_trigger[-1].close
    past_close = past[-1].close   # close cross_lookback bars ago (when the cross printed)
    close_inside_kumo = cloud_bottom <= close <= cloud_top

    obv = on_balance_volume(candles_trigger)
    closes = [c.close for c in candles_trigger]
    swings = detect_swings(candles_bias, fractal_width=fractal_width)
    sr_levels = horizontal_sr(swings, lookback=sr_lookback)

    # ---- LONG: TK crossed up recently while below the cloud, now closes back inside ----
    bullish_cross = p_tenkan <= p_kijun and tenkan > kijun
    was_below = past_close < p_cloud_bottom
    if (bullish_cross and was_below and close_inside_kumo
            and fisher_recent_min <= -exhaustion_threshold
            and _obv_confluence(obv, closes, obv_lookback, True, obv_rule)):
        support = _nearest_support_below(sr_levels, close)
        swing_low = _nearest_swing_low_below(swings, close)
        if support is not None and swing_low is not None \
                and close - support <= support_proximity_atr * atr:
            stop = swing_low - atr_multiplier * atr
            target = cloud_top
            risk = close - stop
            if risk > 0 and target > close:
                return CounterTrendSignal(
                    direction="LONG", entry=close, stop=stop, target_at_entry=target,
                    reward_risk=(target - close) / risk, fisher_value=fisher_recent_min,
                    obv_rule=obv_rule,
                    reason=(f"E2E long: TK cross up into Kumo from below, Fisher reached "
                            f"{fisher_recent_min:.2f} <= -{exhaustion_threshold}, OBV {obv_rule}, "
                            f"at support {support:.2f}"),
                )

    # ---- SHORT: TK crossed down recently while above the cloud, now closes back inside ----
    bearish_cross = p_tenkan >= p_kijun and tenkan < kijun
    was_above = past_close > p_cloud_top
    if (bearish_cross and was_above and close_inside_kumo
            and fisher_recent_max >= exhaustion_threshold
            and _obv_confluence(obv, closes, obv_lookback, False, obv_rule)):
        resistance = _nearest_resistance_above(sr_levels, close)
        swing_high = _nearest_swing_high_above(swings, close)
        if resistance is not None and swing_high is not None \
                and resistance - close <= support_proximity_atr * atr:
            stop = swing_high + atr_multiplier * atr
            target = cloud_bottom
            risk = stop - close
            if risk > 0 and target < close:
                return CounterTrendSignal(
                    direction="SHORT", entry=close, stop=stop, target_at_entry=target,
                    reward_risk=(close - target) / risk, fisher_value=fisher_recent_max,
                    obv_rule=obv_rule,
                    reason=(f"E2E short: TK cross down into Kumo from above, Fisher reached "
                            f"{fisher_recent_max:.2f} >= {exhaustion_threshold}, OBV {obv_rule}, "
                            f"at resistance {resistance:.2f}"),
                )

    return None
