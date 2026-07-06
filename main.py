"""Scheduler loop for the BTC-PERP signal bot (Stage 1, signal-only).

Evaluates strategy logic only on 1H/4H candle closes (build spec section
11: closed candles only — no repainting). No code path in this process
can place an order; execution/propr_stub.py is never invoked from here.

Deploy notes (Railway worker, see Procfile):
- A startup heartbeat is sent immediately on boot so Telegram delivery is
  proven without waiting for the first 4-hour cycle.
- Each poll cycle logs an INFO "alive" line — this is the health-check
  equivalent in Railway logs for a worker with no HTTP server.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import yaml

from alerts.formats import (
    format_daily_summary,
    format_entry_signal,
    format_exit_alert,
    format_halt_alert,
    format_heartbeat,
)
from alerts.telegram import TelegramClient
from data.feed import fetch_candles
from ledger.tracker import Ledger
from risk.circuit_breaker import CircuitBreaker
from strategy.bias_4h import compute_bias
from strategy.signals import Signal, SuppressedSignal, evaluate_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("btc_signal_bot")

POLL_SECONDS = 60  # cheap wall-clock poll; strategy work only runs at candle-close boundaries

# Lookback windows per RESEARCH_FINDINGS 3.4: candleSnapshot is rate-
# weighted per 60 candles returned, so request only what the strategy
# needs (~300 bars), never the 5,000-candle max.
LOOKBACK_1H = timedelta(hours=300)
LOOKBACK_4H = timedelta(hours=4 * 300)


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _last_closed_candle_time(now: datetime, interval_hours: int) -> datetime:
    """Start time (UTC) of the most recently CLOSED candle for the interval.

    Floors `now` to the interval boundary, then steps back one full
    interval — the candle whose start is the current floored boundary is
    still in progress, so it is never returned.
    """
    epoch_hours = int(now.timestamp() // 3600)
    current_open_hour = (epoch_hours // interval_hours) * interval_hours
    last_closed_open_hour = current_open_hour - interval_hours
    return datetime.fromtimestamp(last_closed_open_hour * 3600, tz=timezone.utc)


def run() -> None:
    cfg = load_config()
    telegram = TelegramClient()

    ledger = Ledger(
        starting_equity=cfg["account"]["starting_equity_usd"],
        equity=cfg["account"]["starting_equity_usd"],
        day_start_equity=cfg["account"]["starting_equity_usd"],
    )
    breaker = CircuitBreaker(day_start_equity=ledger.equity)

    last_1h_close_seen: datetime | None = None
    last_heartbeat_at = datetime.now(timezone.utc)
    last_day = datetime.now(timezone.utc).date()
    feed_errors_since_heartbeat = 0
    halt_events_today = 0
    current_bias_label = "NEUTRAL"
    last_data_timestamp = datetime.now(timezone.utc)

    logger.info("btc-signal-bot starting (Stage 1, signal-only)")
    # Startup heartbeat: proves Telegram delivery immediately on boot.
    sent = telegram.send(format_heartbeat(current_bias_label, last_data_timestamp, 0))
    logger.info("startup heartbeat sent=%s", sent)

    while True:
        now = datetime.now(timezone.utc)

        try:
            close_1h = _last_closed_candle_time(now, 1)
            new_1h_close = last_1h_close_seen is None or close_1h > last_1h_close_seen

            candles_1h = fetch_candles(
                cfg["data"]["coin"], cfg["data"]["trigger_interval"],
                _ms(now - LOOKBACK_1H), _ms(now),
            )
            if candles_1h:
                last_data_timestamp = datetime.fromtimestamp(
                    candles_1h[-1].close_time_ms / 1000, tz=timezone.utc
                )

            if new_1h_close and candles_1h:
                candles_4h = fetch_candles(
                    cfg["data"]["coin"], cfg["data"]["bias_interval"],
                    _ms(now - LOOKBACK_4H), _ms(now),
                )
                last_1h_close_seen = close_1h
                if candles_4h:
                    current_bias_label = compute_bias(
                        candles_4h,
                        fractal_width=cfg["strategy"]["fractal_width"],
                        sr_lookback=cfg["strategy"]["sr_lookback"],
                    ).bias.value

                    result = evaluate_signal(candles_4h, candles_1h, now=now)
                    if isinstance(result, Signal):
                        if breaker.is_halted():
                            logger.info("Signal suppressed: circuit breaker halted (%s)", breaker.halt_reason)
                        else:
                            risk_pct = cfg["risk"]["risk_pct"]
                            pos = ledger.open_hypothetical_position(
                                result, risk_pct=risk_pct, sz_decimals=cfg["risk"]["btc_sz_decimals"]
                            )
                            risk_amount = abs(result.entry - result.stop) * pos.quantity
                            telegram.send(format_entry_signal(result, pos.quantity, risk_pct, risk_amount))
                            logger.info("Entry signal alerted: %s @ %s", result.direction.value, result.entry)
                    elif isinstance(result, SuppressedSignal):
                        logger.info("Signal suppressed: %s", result.reason)

            if candles_1h:
                current_price = candles_1h[-1].close
                for closed_pos in ledger.check_exits(current_price, now=now):
                    telegram.send(format_exit_alert(closed_pos, ledger.daily_pnl()))
                    logger.info("Exit alerted: %s %.2fR", closed_pos.exit_reason, closed_pos.pnl_r)

                breaker.update(ledger.current_equity())
                if breaker.just_tripped():
                    halt_events_today += 1
                    telegram.send(format_halt_alert(ledger.daily_pnl_pct()))
                    logger.warning("Circuit breaker tripped: %s", breaker.halt_reason)

            logger.info(
                "alive: bias=%s equity=%.2f open_positions=%d daily_pnl=%.2f halted=%s",
                current_bias_label, ledger.equity, len(ledger.open_positions),
                ledger.daily_pnl(), breaker.is_halted(),
            )

        except Exception:
            feed_errors_since_heartbeat += 1
            logger.warning("Error during evaluation loop", exc_info=True)

        if now.date() > last_day:
            telegram.send(format_daily_summary(ledger.today_stats(), current_bias_label, halt_events_today))
            ledger.start_new_day()
            breaker.reset_for_new_day(ledger.equity)
            halt_events_today = 0
            last_day = now.date()
            logger.info("Daily rollover complete; day_start_equity=%.2f", ledger.day_start_equity)

        if (now - last_heartbeat_at) >= timedelta(hours=cfg["telegram"]["heartbeat_interval_hours"]):
            telegram.send(format_heartbeat(current_bias_label, last_data_timestamp, feed_errors_since_heartbeat))
            last_heartbeat_at = now
            feed_errors_since_heartbeat = 0

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
