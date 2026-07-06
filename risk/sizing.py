"""Position sizing per build spec section 5.

quantity = (equity * risk_pct) / |entry - stop|, truncated down (never
up) to the venue's quantity step (BTC szDecimals — see
docs/RESEARCH_FINDINGS.md 3.4). Inputs are validated with raises, not
silent clamps.
"""
from __future__ import annotations

import math

DEFAULT_RISK_PCT = 0.0075  # 0.75%, per spec's default within the 0.5-1.0% band
MIN_RISK_PCT = 0.005
MAX_RISK_PCT = 0.01
DEFAULT_BTC_SZ_DECIMALS = 5  # fallback only; live value must come from data/feed.get_btc_sz_decimals


def truncate_to_step(quantity: float, sz_decimals: int) -> float:
    """Floor `quantity` to `sz_decimals` decimal places — truncates down, never rounds up."""
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    factor = 10**sz_decimals
    return math.floor(quantity * factor) / factor


def size(
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = DEFAULT_RISK_PCT,
    sz_decimals: int = DEFAULT_BTC_SZ_DECIMALS,
) -> float:
    if equity <= 0:
        raise ValueError("equity must be positive")
    if not (MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT):
        raise ValueError(f"risk_pct {risk_pct} outside allowed band [{MIN_RISK_PCT}, {MAX_RISK_PCT}]")

    risk_per_unit = abs(entry_price - stop_price)
    if risk_per_unit == 0:
        raise ValueError("entry_price and stop_price must differ")

    raw_quantity = (equity * risk_pct) / risk_per_unit
    return truncate_to_step(raw_quantity, sz_decimals)
