"""Timeframe definitions shared by the engine, store validation, and UI.

Single source of truth — no per-interval strategy logic exists anywhere
(strategy functions consume candle sequences and are interval-agnostic).

All intervals here are Hyperliquid-native candleSnapshot intervals
(RESEARCH_FINDINGS 3.4). Note: 4D was requested but is NOT a native
interval — replaced by 1w per user decision (2026-07-07).
"""
from __future__ import annotations

# Hyperliquid-native interval -> seconds
INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
}

# Selectable sets per mode (build spec for /settings)
PRODUCTION_TIMEFRAMES = ("15m", "30m", "1h", "4h", "8h", "12h", "1d", "3d", "1w")
TEST_TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h")

# Strategy needs ~22 closed bars minimum (Fisher 10 + OBV SMA 20 + fractal
# confirmation); default request window in bars.
LOOKBACK_BARS = 300


def interval_seconds(tf: str) -> int:
    try:
        return INTERVAL_SECONDS[tf]
    except KeyError:
        raise ValueError(f"unknown timeframe {tf!r} — allowed: {sorted(INTERVAL_SECONDS)}") from None


def validate_combo(bias_tf: str, trigger_tf: str) -> None:
    """Bias must be a strictly longer timeframe than trigger."""
    if interval_seconds(bias_tf) <= interval_seconds(trigger_tf):
        raise ValueError(
            f"bias timeframe {bias_tf} must be longer than trigger timeframe {trigger_tf}"
        )
