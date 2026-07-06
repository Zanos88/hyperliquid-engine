"""Scheduler loop for the BTC-PERP signal bot (Stage 1, signal-only).

SCAFFOLD ONLY — evaluates strategy logic only on 1H/4H candle closes (per
build spec section 11: "all strategy decisions evaluate on closed candles
only"). No code path in this process may call execution/propr_stub.py
except via feature_flags.execution_enabled, which Stage 1 keeps hard-off.
See docs/STRATEGY_PSEUDOCODE.md for the full event-driven flow this loop
implements (4H bias update, 1H trigger, exit checks, daily rollover,
heartbeat).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import yaml

from alerts.formats import format_daily_summary, format_entry_signal, format_exit_alert, format_halt_alert, format_heartbeat
from alerts.telegram import TelegramClient
from data.feed import fetch_candles
from ledger.tracker import Ledger
from risk.circuit_breaker import CircuitBreaker
from strategy.signals import SuppressedSignal, evaluate_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("btc_signal_bot")

POLL_SECONDS = 60  # cheap wall-clock poll; actual work only runs at candle-close boundaries


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _last_closed_candle_time(now: datetime, interval_hours: int) -> datetime:
    """TODO(Fable): return the start time (UTC) of the most recently CLOSED
    candle for the given interval_hours, given `now`. Must never return a
    time that could still be in-progress."""
    raise NotImplementedError


def run() -> None:
    """TODO(Fable): implement the main loop per docs/STRATEGY_PSEUDOCODE.md:

    1. Load config, construct TelegramClient, Ledger, CircuitBreaker.
    2. Every POLL_SECONDS: if a new 1H candle has closed, fetch 4H+1H
       candles via data.feed.fetch_candles and call
       strategy.signals.evaluate_signal. On a real Signal (not
       SuppressedSignal/None) and breaker not halted: open a hypothetical
       position via ledger, send the entry alert.
    3. Every loop: check ledger.check_exits against latest price, send
       exit alerts; update the circuit breaker and send a HALT alert on
       breaker.just_tripped().
    4. On UTC day rollover: send the daily summary, ledger.start_new_day(),
       breaker.reset_for_new_day().
    5. Every telegram.heartbeat_interval_hours: send a heartbeat, resetting
       the feed-error counter.

    Wrap the per-iteration work in try/except and log a WARNING (never
    silently swallow) on any feed/strategy error, incrementing the
    feed-error counter surfaced in the next heartbeat.
    """
    raise NotImplementedError


if __name__ == "__main__":
    run()
