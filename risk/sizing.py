"""Position sizing — Stage 1 fixed fraction + V2 static-floor attenuation.

V2 (build report section 5): the Kelly core from the source docs is
rejected (no trade history to estimate p); sizing is fixed-fraction with
a static-floor attenuation term:

    risk_usd    = equity × risk_pct × attenuation
    attenuation = ((equity − 94_000) / (peak_equity − 94_000)) ** alpha
    quantity    = risk_usd / |entry − stop|   (truncated DOWN to venue step)

At peak equity attenuation = 1.0 (full risk); in drawdown it decays
smoothly so consecutive losses cannot walk equity to the floor.

Bounds are 0.25–1.0% per the V2 report (user-approved widening of the
Stage 1 0.5% floor; the Stage 1 test contract is unaffected — its bounds
test exercises the max, not the floor).
"""
from __future__ import annotations

import math

DEFAULT_RISK_PCT = 0.0075   # 0.75%
MIN_RISK_PCT = 0.0025       # 0.25% (V2 report /risk bounds; widened from Stage 1's 0.5%)
MAX_RISK_PCT = 0.01         # 1.0%
DEFAULT_BTC_SZ_DECIMALS = 5  # fallback only; live value from data/feed.get_btc_sz_decimals
STATIC_FLOOR_USD = 94_000.0  # Propr Gold 1-Step Classic 6% static floor — VERIFIED live (drawdownType=static)
DEFAULT_ALPHA = 1.5          # attenuation exponent, alpha >= 1.0


def truncate_to_step(quantity: float, sz_decimals: int) -> float:
    """Floor `quantity` to `sz_decimals` decimal places — truncates down, never rounds up."""
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    factor = 10**sz_decimals
    return math.floor(quantity * factor) / factor


def attenuation(equity: float, peak_equity: float, alpha: float = DEFAULT_ALPHA,
                floor: float = STATIC_FLOOR_USD) -> float:
    """Static-floor attenuation in [0, 1]. Never raises on degenerate inputs.

    Edge cases (explicit, no div-by-zero / complex-number paths):
    - equity at/below the floor -> 0.0 (no risk budget left)
    - peak at/below the floor   -> 0.0 (degenerate; peak should never be
      below equity, but a broken peak feed must fail SAFE, i.e. to zero)
    - equity above peak (stale peak) -> clamped to 1.0
    """
    if alpha < 1.0:
        raise ValueError("alpha must be >= 1.0 (attenuation must not amplify risk)")
    if equity <= floor or peak_equity <= floor:
        return 0.0
    base = (equity - floor) / (peak_equity - floor)
    base = max(0.0, min(base, 1.0))
    return base**alpha


def size(
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = DEFAULT_RISK_PCT,
    sz_decimals: int = DEFAULT_BTC_SZ_DECIMALS,
) -> float:
    """Stage 1 fixed-fraction size (no attenuation). Kept for the paper ledger."""
    if equity <= 0:
        raise ValueError("equity must be positive")
    if not (MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT):
        raise ValueError(f"risk_pct {risk_pct} outside allowed band [{MIN_RISK_PCT}, {MAX_RISK_PCT}]")

    risk_per_unit = abs(entry_price - stop_price)
    if risk_per_unit == 0:
        raise ValueError("entry_price and stop_price must differ")

    raw_quantity = (equity * risk_pct) / risk_per_unit
    return truncate_to_step(raw_quantity, sz_decimals)


def size_attenuated(
    equity: float,
    peak_equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = DEFAULT_RISK_PCT,
    alpha: float = DEFAULT_ALPHA,
    sz_decimals: int = DEFAULT_BTC_SZ_DECIMALS,
) -> tuple[float, float, float]:
    """V2 sizing: returns (quantity, risk_usd, attenuation_applied).

    quantity is truncated down to the venue step; risk_usd reflects the
    PRE-truncation risk budget (the ledger records both, plus the actual
    at-stop risk implied by the truncated quantity).
    """
    if equity <= 0:
        raise ValueError("equity must be positive")
    if not (MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT):
        raise ValueError(f"risk_pct {risk_pct} outside allowed band [{MIN_RISK_PCT}, {MAX_RISK_PCT}]")

    risk_per_unit = abs(entry_price - stop_price)
    if risk_per_unit == 0:
        raise ValueError("entry_price and stop_price must differ")

    att = attenuation(equity, peak_equity, alpha=alpha)
    risk_usd = equity * risk_pct * att
    raw_quantity = risk_usd / risk_per_unit
    return truncate_to_step(raw_quantity, sz_decimals), risk_usd, att
