"""Hypothetical position ledger per build spec section 4.3 / 7.

SCAFFOLD ONLY — Stage 1 never places real orders; this tracks the bot's
own paper positions so the Telegram channel forms a complete auditable
ledger, and so the circuit breaker has a real P&L series to gate on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from risk.sizing import size as compute_size
from strategy.signals import Signal, SignalDirection


@dataclass
class OpenPosition:
    signal: Signal
    quantity: float
    opened_at: datetime


@dataclass
class ClosedPosition:
    signal: Signal
    quantity: float
    opened_at: datetime
    closed_at: datetime
    exit_price: float
    exit_reason: str  # "stop" or "target"
    pnl: float
    pnl_r: float


@dataclass
class Ledger:
    starting_equity: float
    equity: float
    day_start_equity: float
    open_positions: list[OpenPosition] = field(default_factory=list)
    closed_today: list[ClosedPosition] = field(default_factory=list)
    all_closed: list[ClosedPosition] = field(default_factory=list)

    def current_equity(self) -> float:
        return self.equity

    def day_start(self) -> float:
        return self.day_start_equity

    def daily_pnl(self) -> float:
        return self.equity - self.day_start_equity

    def daily_pnl_pct(self) -> float:
        return self.daily_pnl() / self.day_start_equity

    def open_hypothetical_position(self, signal: Signal, risk_pct: float, sz_decimals: int) -> OpenPosition:
        """TODO(Fable): compute_size(...) then append/return an OpenPosition."""
        raise NotImplementedError

    def check_exits(self, current_price: float, now: datetime | None = None) -> list[ClosedPosition]:
        """TODO(Fable): for each open position, check stop/target touch
        (direction-aware: LONG closes on price<=stop or price>=target,
        SHORT is mirrored), compute pnl and pnl_r, move it from
        open_positions into closed_today/all_closed, update self.equity,
        and return the list of positions closed this call.
        """
        raise NotImplementedError

    def start_new_day(self) -> None:
        """TODO(Fable): day_start_equity = equity; clear closed_today."""
        raise NotImplementedError

    def today_stats(self) -> dict:
        """TODO(Fable): return signals_fired, closed_trades, wins, win_rate,
        daily_pnl, daily_pnl_pct, equity — used by the daily summary alert."""
        raise NotImplementedError
