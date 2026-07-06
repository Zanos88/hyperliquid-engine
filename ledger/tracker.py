"""Hypothetical position ledger per build spec section 4.3 / 7.

Stage 1 never places real orders — this tracks the bot's own paper
positions so the Telegram channel forms a complete auditable ledger, and
so the circuit breaker has a real P&L series to gate on.
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
        qty = compute_size(self.equity, signal.entry, signal.stop, risk_pct=risk_pct, sz_decimals=sz_decimals)
        pos = OpenPosition(signal=signal, quantity=qty, opened_at=datetime.now(timezone.utc))
        self.open_positions.append(pos)
        return pos

    def check_exits(self, current_price: float, now: datetime | None = None) -> list[ClosedPosition]:
        now = now or datetime.now(timezone.utc)
        closed: list[ClosedPosition] = []
        still_open: list[OpenPosition] = []

        for pos in self.open_positions:
            s = pos.signal
            hit_stop = (
                current_price <= s.stop if s.direction == SignalDirection.LONG else current_price >= s.stop
            )
            hit_target = (
                current_price >= s.target if s.direction == SignalDirection.LONG else current_price <= s.target
            )

            if hit_stop or hit_target:
                exit_price = s.stop if hit_stop else s.target
                reason = "stop" if hit_stop else "target"
                direction_sign = 1 if s.direction == SignalDirection.LONG else -1
                pnl = direction_sign * (exit_price - s.entry) * pos.quantity
                risk_amount = abs(s.entry - s.stop) * pos.quantity
                pnl_r = pnl / risk_amount if risk_amount else 0.0

                closed_pos = ClosedPosition(
                    signal=s, quantity=pos.quantity, opened_at=pos.opened_at, closed_at=now,
                    exit_price=exit_price, exit_reason=reason, pnl=pnl, pnl_r=pnl_r,
                )
                closed.append(closed_pos)
                self.closed_today.append(closed_pos)
                self.all_closed.append(closed_pos)
                self.equity += pnl
            else:
                still_open.append(pos)

        self.open_positions = still_open
        return closed

    def start_new_day(self) -> None:
        self.day_start_equity = self.equity
        self.closed_today = []

    def today_stats(self) -> dict:
        wins = [c for c in self.closed_today if c.pnl > 0]
        return {
            "signals_fired": len(self.closed_today) + len(self.open_positions),
            "closed_trades": len(self.closed_today),
            "wins": len(wins),
            "win_rate": (len(wins) / len(self.closed_today)) if self.closed_today else None,
            "daily_pnl": self.daily_pnl(),
            "daily_pnl_pct": self.daily_pnl_pct(),
            "equity": self.equity,
        }
