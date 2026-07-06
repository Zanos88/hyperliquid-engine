"""Position sizing per build spec section 5.

SCAFFOLD ONLY — quantity = (equity * risk_pct) / |entry - stop|, truncated
down (never up) to the venue's quantity step (BTC szDecimals — see
docs/RESEARCH_FINDINGS.md 3.4). Implement with validation on inputs
(equity > 0, risk_pct within band, entry != stop) — raise, don't silently
clamp.
"""
from __future__ import annotations

DEFAULT_RISK_PCT = 0.0075  # 0.75%, per spec's default within the 0.5-1.0% band
MIN_RISK_PCT = 0.005
MAX_RISK_PCT = 0.01
DEFAULT_BTC_SZ_DECIMALS = 5  # cited default; prefer a live meta lookup (data/feed.get_btc_sz_decimals)


def truncate_to_step(quantity: float, sz_decimals: int) -> float:
    """TODO(Fable): floor `quantity` to `sz_decimals` decimal places (truncate down)."""
    raise NotImplementedError


def size(
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = DEFAULT_RISK_PCT,
    sz_decimals: int = DEFAULT_BTC_SZ_DECIMALS,
) -> float:
    """TODO(Fable): implement per build spec section 5.

    Validate: equity > 0; MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT;
    entry_price != stop_price (raise ValueError otherwise, do not clamp).
    quantity = (equity * risk_pct) / abs(entry_price - stop_price), then
    truncate_to_step(quantity, sz_decimals).
    """
    raise NotImplementedError
