"""Hard pre-trade gate — V2 build report section 5.

Every execution path (engine signals AND every Telegram button) must pass
through `evaluate_gate` before any order intent is created. All checks
must pass; every failure is named in `reasons` (no silent rejection).

Binding floor = max(day_start_equity − 3_000, 94_000) — both limits
verified live (Gold 1-Step Classic: maxDailyLossPercent=3,
maxDrawdownPercent=6, drawdownType=static).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from risk.sizing import (
    DEFAULT_ALPHA,
    DEFAULT_BTC_SZ_DECIMALS,
    DEFAULT_RISK_PCT,
    STATIC_FLOOR_USD,
    size_attenuated,
)
from strategy.signals import Signal

DAILY_LOSS_LIMIT_USD = 3_000.0
MIN_REWARD_RISK = 2.0
VENUE_MIN_QTY_BTC = 0.001  # verified: api.md Available Assets
DEFAULT_SOFT_BUFFER_USD = 500.0
DEFAULT_MAX_CONCURRENT = 1


def binding_floor(day_start_equity: float) -> float:
    return max(day_start_equity - DAILY_LOSS_LIMIT_USD, STATIC_FLOOR_USD)


@dataclass(frozen=True)
class GateDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)  # empty when approved
    quantity: float = 0.0
    risk_usd: float = 0.0
    attenuation_applied: float = 0.0
    worst_case_equity: float = 0.0
    binding_floor: float = 0.0


def evaluate_gate(
    engine_state: str,
    signal: Signal,
    equity: float,
    peak_equity: float,
    day_start_equity: float,
    open_positions_count: int,
    risk_pct: float = DEFAULT_RISK_PCT,
    alpha: float = DEFAULT_ALPHA,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    sz_decimals: int = DEFAULT_BTC_SZ_DECIMALS,
    soft_buffer_usd: float = DEFAULT_SOFT_BUFFER_USD,
) -> GateDecision:
    """All-must-pass pre-trade gate. Returns a decision with named reasons."""
    reasons: list[str] = []
    floor = binding_floor(day_start_equity)

    if engine_state != "ACTIVE":
        reasons.append(f"engine state is {engine_state}, not ACTIVE")

    if signal.reward_risk < MIN_REWARD_RISK:
        reasons.append(f"R:R {signal.reward_risk:.2f} below minimum {MIN_REWARD_RISK}")

    if open_positions_count >= max_concurrent:
        reasons.append(f"max concurrent positions reached ({open_positions_count}/{max_concurrent})")

    quantity = risk_usd = att = 0.0
    try:
        quantity, risk_usd, att = size_attenuated(
            equity=equity, peak_equity=peak_equity,
            entry_price=signal.entry, stop_price=signal.stop,
            risk_pct=risk_pct, alpha=alpha, sz_decimals=sz_decimals,
        )
    except ValueError as exc:
        reasons.append(f"sizing rejected: {exc}")

    if quantity < VENUE_MIN_QTY_BTC:
        reasons.append(
            f"quantity {quantity} below venue minimum {VENUE_MIN_QTY_BTC} after truncation "
            f"(attenuation {att:.4f})"
        )

    # Worst case: stopped out at the stop price with the truncated quantity.
    actual_risk_at_stop = abs(signal.entry - signal.stop) * quantity
    worst_case_equity = equity - actual_risk_at_stop
    if worst_case_equity <= floor + soft_buffer_usd:
        reasons.append(
            f"worst-case equity {worst_case_equity:,.2f} would not clear binding floor "
            f"{floor:,.2f} + soft buffer {soft_buffer_usd:,.0f}"
        )

    return GateDecision(
        approved=not reasons,
        reasons=reasons,
        quantity=quantity,
        risk_usd=risk_usd,
        attenuation_applied=att,
        worst_case_equity=worst_case_equity,
        binding_floor=floor,
    )
