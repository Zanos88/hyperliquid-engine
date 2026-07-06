"""Scheduler loop for the BTC-PERP signal bot (Stage 1, signal-only).

Evaluates strategy logic only on 1H/4H candle closes (per build spec
section 11: "all strategy decisions evaluate on closed candles only").
No code path in this process can place an order — execution/propr_stub.py
is never invoked from here.
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
    epoch_hours = int(now.timestamp() // 3600)
    closed_hour = (epoch_hours // interval_hours) * interval_hours
    return datetime.fromtimestamp(closed_hour * 3600, tz=timezone.utc)


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
    last_4h_close_seen: datetime | None = None
    last_heartbeat_at = datetime.now(timezone.utc)
    last_day = datetime.now(timezone.utc).date()
    feed_errors_since_heartbeat = 0
    halt_events_today = 0
    current_bias_label = "NEUTRAL"

    logger.info("btc-signal-bot starting (Stage 1, signal-only)")

    while True:
        now = datetime.now(timezone.utc)

        try:
            close_4h = _last_closed_candle_time(now, 4)
            close_1h = _last_closed_candle_time(now, 1)

            candles_4h = fetch_candles(
                cfg["data"]["coin"], cfg["data"]["bias_interval"],
                _ms(now - timedelta(days=60)), _ms(now),
            )
            candles_1h = fetch_candles(
                cfg["data"]["coin"], cfg["data"]["trigger_interval"],
                _ms(now - timedelta(days=10)), _ms(now),
            )

            new_1h_close = last_1h_close_seen is None or close_1h > last_1h_close_seen
            if new_1h_close and candles_4h and candles_1h:
                last_1h_close_seen = close_1h
                last_4h_close_seen = close_4h

                result = evaluate_signal(candles_4h, candles_1h, now=now)
                if result is not None and not isinstance(result, SuppressedSignal):
                    if breaker.is_halted():
                        logger.info("Signal suppressed: circuit breaker halted")
                    else:
                        risk_pct = cfg["risk"]["risk_pct"]
                        pos = ledger.open_hypothetical_position(
                            result, risk_pct=risk_pct, sz_decimals=cfg["risk"]["btc_sz_decimals"]
                        )
                        risk_amount = ledger.equity * risk_pct
                        telegram.send(format_entry_signal(result, pos.quantity, risk_pct, risk_amount))
                elif isinstance(result, SuppressedSignal):
                    logger.info("Signal suppressed: %s", result.reason)

            current_price = candles_1h[-1].close if candles_1h else None
            if current_price is not None:
                closed = ledger.check_exits(current_price, now=now)
                for c in closed:
                    telegram.send(format_exit_alert(c, ledger.daily_pnl()))

                breaker.update(ledger.current_equity())
                if breaker.just_tripped():
                    halt_events_today += 1
                    telegram.send(format_halt_alert(ledger.daily_pnl_pct()))

        except Exception:
            feed_errors_since_heartbeat += 1
            logger.warning("Error during evaluation loop", exc_info=True)

        if now.date() > last_day:
            telegram.send(format_daily_summary(ledger.today_stats(), current_bias_label, halt_events_today))
            ledger.start_new_day()
            breaker.reset_for_new_day(ledger.equity)
            halt_events_today = 0
            last_day = now.date()

        if (now - last_heartbeat_at) >= timedelta(hours=cfg["telegram"]["heartbeat_interval_hours"]):
            telegram.send(format_heartbeat(current_bias_label, now, feed_errors_since_heartbeat))
            last_heartbeat_at = now
            feed_errors_since_heartbeat = 0

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
