"""Daily circuit breaker per build spec section 6.

SCAFFOLD ONLY — halts new signal generation at -2.5% daily P&L, a
deliberate buffer inside the challenge's real 3% daily loss limit.
HALT_THRESHOLD_PCT must stay a hard-coded constant, never read from
config.yaml, so it cannot be casually widened (build spec sections 6/11).
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
        """TODO(Fable): recompute halt state from current (equity-inclusive)
        daily P&L. Set self._just_tripped True only on the transition into
        halted (not on every subsequent update while already halted) so
        the caller sends exactly one HALT alert per breach.
        Raise ValueError if day_start_equity <= 0.
        """
        raise NotImplementedError

    def just_tripped(self) -> bool:
        return self._just_tripped

    def is_halted(self) -> bool:
        return self.halted

    def reset_for_new_day(self, new_day_start_equity: float) -> None:
        """TODO(Fable): reset day_start_equity, halted, halt_reason, _just_tripped."""
        raise NotImplementedError


def is_new_utc_day(last_timestamp: datetime, now: datetime | None = None) -> bool:
    """TODO(Fable): True if `now` (default utcnow) is on a later UTC calendar
    date than `last_timestamp`."""
    raise NotImplementedError
