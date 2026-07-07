"""Engine — Stage 2 scheduler (signal -> gate -> dry-run execution).

Evaluates strategy logic only on 1H/4H candle closes (closed candles
only). Every approved entry routes through the risk gate; intents are
recorded to Postgres BEFORE any dispatch (the floor-guard trigger is the
last line of defense) and the execution service is dry-run by default —
V2 dispatches nothing live.

The Stage 1 paper ledger stays as the dry-run P&L source: it drives the
circuit breaker, telemetry, daily summary, and heartbeat exactly as
before. Engine state (ACTIVE/PAUSED/KILLED) is shared cross-process via
Postgres and controlled by the Telegram control plane and guardian.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import yaml
from ulid import ULID

from alerts.formats import (
    format_daily_summary,
    format_entry_signal,
    format_exit_alert,
    format_halt_alert,
    format_heartbeat,
)
from alerts.telegram import TelegramClient
from data.feed import fetch_candles
from db.store import TelemetryStore
from execution.propr_client import ProprExecutionService
from ledger.tracker import Ledger
from risk.circuit_breaker import CircuitBreaker
from risk.gate import evaluate_gate
from strategy.bias_4h import compute_bias
from strategy.signals import Signal, SuppressedSignal, evaluate_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("btc_signal_bot")

POLL_SECONDS = 60
LOOKBACK_1H = timedelta(hours=300)
LOOKBACK_4H = timedelta(hours=4 * 300)


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _last_closed_candle_time(now: datetime, interval_hours: int) -> datetime:
    epoch_hours = int(now.timestamp() // 3600)
    current_open_hour = (epoch_hours // interval_hours) * interval_hours
    return datetime.fromtimestamp((current_open_hour - interval_hours) * 3600, tz=timezone.utc)


def frame_a_markup(signal_id: str) -> dict:
    """Frame A: risk-% buttons only — fixed-notional buttons are rejected
    by design (V2 report section 4)."""
    return {"inline_keyboard": [[
        {"text": "Take @ 0.75% risk", "callback_data": f"take_0.75_{signal_id}"},
        {"text": "Take @ 0.5%", "callback_data": f"take_0.5_{signal_id}"},
        {"text": "Skip", "callback_data": f"skip_{signal_id}"},
    ]]}


def run() -> None:
    cfg = load_config()
    telegram = TelegramClient()
    store = TelemetryStore()
    store.apply_schema()
    execution = ProprExecutionService(
        execution_enabled=bool(cfg.get("feature_flags", {}).get("execution_enabled", False)),
    )

    ledger = Ledger(
        starting_equity=cfg["account"]["starting_equity_usd"],
        equity=cfg["account"]["starting_equity_usd"],
        day_start_equity=cfg["account"]["starting_equity_usd"],
    )
    breaker = CircuitBreaker(day_start_equity=ledger.equity)
    peak_equity = ledger.equity

    last_1h_close_seen: datetime | None = None
    last_heartbeat_at = datetime.now(timezone.utc)
    last_day = datetime.now(timezone.utc).date()
    feed_errors_since_heartbeat = 0
    halt_events_today = 0
    current_bias_label = "NEUTRAL"
    last_data_timestamp = datetime.now(timezone.utc)
    latest_indicators: dict = {}

    logger.info("engine starting (Stage 2, DRY-RUN execution; state=%s)", store.get_engine_state())
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
                    bias_result = compute_bias(
                        candles_4h,
                        fractal_width=cfg["strategy"]["fractal_width"],
                        sr_lookback=cfg["strategy"]["sr_lookback"],
                    )
                    current_bias_label = bias_result.bias.value
                    latest_indicators = {"bias": current_bias_label, "bias_reason": bias_result.reason}

                    result = evaluate_signal(candles_4h, candles_1h, now=now)
                    if isinstance(result, Signal):
                        _handle_signal(result, cfg, store, execution, telegram, ledger,
                                       breaker, peak_equity, latest_indicators)
                    elif isinstance(result, SuppressedSignal):
                        logger.info("Signal suppressed: %s", result.reason)

            if candles_1h:
                current_price = candles_1h[-1].close
                for closed_pos in ledger.check_exits(current_price, now=now):
                    telegram.send(format_exit_alert(closed_pos, ledger.daily_pnl()))
                    logger.info("Paper exit: %s %.2fR", closed_pos.exit_reason, closed_pos.pnl_r)

                peak_equity = max(peak_equity, ledger.equity)
                breaker.update(ledger.current_equity())
                if breaker.just_tripped():
                    halt_events_today += 1
                    telegram.send(format_halt_alert(ledger.daily_pnl_pct()))
                    store.record_risk_event("circuit_breaker_trip", {
                        "daily_pnl_pct": ledger.daily_pnl_pct(), "equity": ledger.equity,
                    })
                    logger.warning("Circuit breaker tripped: %s", breaker.halt_reason)

                store.record_telemetry(
                    equity=ledger.equity, day_start_equity=ledger.day_start_equity,
                    engine_state=store.get_engine_state(),
                )

            logger.info(
                "alive: state=%s bias=%s equity=%.2f open=%d daily_pnl=%.2f cb_halted=%s",
                store.get_engine_state(), current_bias_label, ledger.equity,
                len(ledger.open_positions), ledger.daily_pnl(), breaker.is_halted(),
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


def _handle_signal(signal: Signal, cfg, store, execution, telegram, ledger,
                   breaker, peak_equity: float, indicators: dict) -> None:
    """Gate the signal; post Frame A; auto-take (dry-run) when ACTIVE."""
    engine_state = store.get_engine_state()
    params = store.get_risk_params()

    if breaker.is_halted():
        logger.info("Signal blocked by circuit breaker (%s)", breaker.halt_reason)
        return

    decision = evaluate_gate(
        engine_state, signal,
        equity=ledger.equity, peak_equity=peak_equity,
        day_start_equity=ledger.day_start_equity,
        open_positions_count=len(ledger.open_positions),
        risk_pct=params["risk_pct"], alpha=params["alpha"],
        max_concurrent=params["max_concurrent"],
        sz_decimals=cfg["risk"]["btc_sz_decimals"],
    )

    signal_id = str(ULID())
    store.create_pending_signal(
        signal_id, signal.direction.value, signal.entry, signal.stop,
        signal.target, signal.reward_risk,
    )
    risk_amount = abs(signal.entry - signal.stop) * decision.quantity
    alert_text = format_entry_signal(signal, decision.quantity, params["risk_pct"], risk_amount)

    if not decision.approved:
        telegram.send(alert_text + "\n⚠️ GATE REJECTED:\n- " + "\n- ".join(decision.reasons),
                      reply_markup=frame_a_markup(signal_id))
        logger.info("Gate rejected signal: %s", decision.reasons)
        return

    if engine_state == "ACTIVE":
        # Record-before-dispatch: the sink writes the intent row; a floor-
        # guard block raises and aborts dispatch entirely.
        def sink(intent):
            ok = store.record_intent(
                intent, dry_run=execution.dry_run,
                risk_usd=decision.risk_usd,
                attenuation_applied=decision.attenuation_applied,
                indicators_snapshot=indicators,
            )
            if not ok:
                raise RuntimeError(f"floor-guard trigger blocked intent {intent.intent_id}")

        execution._intent_sink = sink
        try:
            result = execution.create_entry_with_bracket(
                direction=signal.direction.value.lower(),
                quantity=str(decision.quantity),
                stop_trigger=str(signal.stop),
                target_trigger=str(signal.target),
                entry_ref_price=str(signal.entry),
            )
            store.resolve_pending_signal(signal_id, "taken", resolved_by="engine:auto")
            ledger.open_hypothetical_position(
                signal, risk_pct=params["risk_pct"], sz_decimals=cfg["risk"]["btc_sz_decimals"]
            )
            telegram.send(alert_text + f"\n\U0001F916 AUTO-TAKEN (dry_run={result.dry_run}, "
                                       f"attenuation {decision.attenuation_applied:.3f})")
            logger.info("Signal auto-taken (dry_run=%s)", result.dry_run)
        except RuntimeError as exc:
            telegram.send(alert_text + f"\n\U0001F6D1 BLOCKED BY FLOOR GUARD: {exc}")
            logger.warning("Floor guard blocked auto-take: %s", exc)
        finally:
            execution._intent_sink = None
    else:
        telegram.send(alert_text + f"\n(engine {engine_state} — manual Take/Skip below)",
                      reply_markup=frame_a_markup(signal_id))
        logger.info("Signal posted for manual take (engine %s)", engine_state)


if __name__ == "__main__":
    run()
