"""Daily circuit breaker per build spec section 6.

Halts new signal generation at -2.5% daily P&L — a deliberate buffer
inside the challenge's real 3% daily loss limit. HALT_THRESHOLD_PCT is a
hard-coded constant, deliberately NOT read from config.yaml, so it cannot
be casually widened (build spec sections 6/11).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

HALT_THRESHOLD_PCT = -0.025  # -2.5%, hard-coded per spec; do not make configurable


@dataclass
class CircuitBreaker:
    day_start_equity: float
    halted: bool = False
    halt_reason: str | None = None
    _just_tripped: bool = field(default=False, repr=False)

    def update(self, current_equity: float) -> None:
        """Recompute halt state from current (equity-inclusive) daily P&L.

        `_just_tripped` is True only on the transition into halted so the
        caller sends exactly one HALT alert per breach, not one per poll.
        """
        if self.day_start_equity <= 0:
            raise ValueError("day_start_equity must be positive")

        daily_pnl_pct = (current_equity - self.day_start_equity) / self.day_start_equity
        was_halted = self.halted

        if daily_pnl_pct <= HALT_THRESHOLD_PCT and not self.halted:
            self.halted = True
            self.halt_reason = f"daily P&L {daily_pnl_pct:.4%} breached halt threshold {HALT_THRESHOLD_PCT:.2%}"

        self._just_tripped = self.halted and not was_halted

    def just_tripped(self) -> bool:
        return self._just_tripped

    def is_halted(self) -> bool:
        return self.halted

    def reset_for_new_day(self, new_day_start_equity: float) -> None:
        self.day_start_equity = new_day_start_equity
        self.halted = False
        self.halt_reason = None
        self._just_tripped = False


def is_new_utc_day(last_timestamp: datetime, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return now.date() > last_timestamp.date()
