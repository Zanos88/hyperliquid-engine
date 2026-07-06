"""Alert message templates. Standalone — no imports from any other repo.

SCAFFOLD ONLY. Per explicit user instruction: this must not import from,
or be copied out of, Bullphoric's alerts/formats.py. It may follow a
broadly similar structural pattern (emoji header, labeled fields) purely
because that is a generic, reasonable shape for a Telegram trading alert
— write it standalone. See build spec section 8 for the four required
alert types and their example layout.
"""
from __future__ import annotations

from datetime import datetime

from ledger.tracker import ClosedPosition
from strategy.signals import Signal


def format_entry_signal(signal: Signal, quantity: float, risk_pct: float, risk_amount: float) -> str:
    """TODO(Fable): render per build spec section 8 example:
    direction, 4H bias reason, 1H trigger reason, entry/stop/target + R:R,
    size + $ risk + risk_pct, UTC timestamp.
    """
    raise NotImplementedError


def format_exit_alert(closed: ClosedPosition, running_daily_pnl: float) -> str:
    """TODO(Fable): stop-or-target result in R and $, plus running daily P&L."""
    raise NotImplementedError


def format_daily_summary(stats: dict, current_bias: str, halt_events_today: int) -> str:
    """TODO(Fable): signals fired, hypothetical P&L, win rate, circuit-breaker
    events, current bias — posted at 00:00 UTC rollover."""
    raise NotImplementedError


def format_heartbeat(current_bias: str, last_data_timestamp: datetime, feed_errors_since_last: int) -> str:
    """TODO(Fable): "alive" status, current 4H bias, last data timestamp,
    feed errors since last heartbeat. Posted every 4 hours — silence is failure."""
    raise NotImplementedError


def format_halt_alert(daily_pnl_pct: float) -> str:
    """TODO(Fable): clearly-labeled HALT alert per build spec section 6."""
    raise NotImplementedError
