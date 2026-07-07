"""Engine — Stage 2 scheduler (signal -> gate -> dry-run execution).

Timeframes and mode are DB-backed (`strategy_settings`, set live via the
/settings control-plane menu) and re-read every cycle. Candle-close
detection is DATA-DRIVEN: a new trigger-timeframe close is detected when
the newest CLOSED candle's open_time changes — robust for every native
interval (15m through 1w) without epoch-boundary assumptions. All
strategy decisions still evaluate on closed candles only.

Every outgoing alert is decorated with the active timeframe combo, and
prefixed [TEST MODE] when mode=test, so a switched config is always
traceable in channel history.
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
from strategy.signals import Signal, SuppressedSignal, evaluate_signal, manual_entry_levels
from strategy.timeframes import LOOKBACK_BARS, interval_seconds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("btc_signal_bot")

POLL_SECONDS = 60


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def lookback_ms(tf: str, bars: int = LOOKBACK_BARS) -> int:
    """Request window: `bars` x interval. Hyperliquid returns what exists
    (1w history is ~150 bars — still >= the ~22-bar indicator minimum)."""
    return bars * interval_seconds(tf) * 1000


def newest_closed_open_time(candles) -> int | None:
    """Data-driven close marker: the open_time of the newest CLOSED candle
    (data/feed.fetch_candles already guarantees only closed candles)."""
    return candles[-1].open_time_ms if candles else None


def decorate(text: str, settings: dict) -> str:
    """Uniform alert decoration (build requirement: every alert states the
    active combo; test-mode alerts are unmistakably labeled)."""
    prefix = "\U0001F9EA <b>[TEST MODE]</b>\n\n" if settings["mode"] == "test" else ""
    suffix = (f"\n<i>TF: {settings['active_bias_tf']} bias / "
              f"{settings['active_trigger_tf']} trigger ({settings['mode']})</i>")
    return prefix + text + suffix


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

    last_trigger_open_seen: int | None = None
    active_combo_seen: tuple[str, str] | None = None
    prev_alignment: str | None = None  # edge-trigger memory for state-based confluence
    latest_levels: dict = {}
    latest_price: float | None = None

    def position_line() -> str:
        if not ledger.open_positions:
            return "none"
        p = ledger.open_positions[0]
        s = p.signal
        upnl = ((latest_price - s.entry) if s.direction.value == "LONG" else (s.entry - latest_price)) * p.quantity \
            if latest_price else 0.0
        return (f"{s.direction.value} {p.quantity:.5f} BTC @ ${s.entry:,.2f} "
                f"(uPnL ${upnl:+,.2f}, paper)")

    def alert_context(readings: dict | None = None, settings: dict | None = None) -> dict:
        """Everything the structured formatters surface — assembled from
        state the engine already holds; nothing recomputed."""
        s = settings or {}
        return {
            "trigger_tf": s.get("active_trigger_tf"), "bias_tf": s.get("active_bias_tf"),
            "readings": readings or latest_indicators.get("readings"),
            "equity": ledger.equity, "day_start_equity": ledger.day_start_equity,
            "open_positions": len(ledger.open_positions),
            "position_line": position_line(),
            "last_price": latest_price, "levels": latest_levels,
        }
    last_heartbeat_at = datetime.now(timezone.utc)
    last_day = datetime.now(timezone.utc).date()
    feed_errors_since_heartbeat = 0
    halt_events_today = 0
    current_bias_label = "NEUTRAL"
    last_data_timestamp = datetime.now(timezone.utc)
    latest_indicators: dict = {}

    settings = store.get_strategy_settings()
    logger.info("engine starting (Stage 2, DRY-RUN execution; state=%s mode=%s tf=%s/%s)",
                store.get_engine_state(), settings["mode"],
                settings["active_bias_tf"], settings["active_trigger_tf"])
    sent = telegram.send(decorate(
        format_heartbeat(current_bias_label, last_data_timestamp, 0,
                         context=alert_context(settings=settings)), settings))
    logger.info("startup heartbeat sent=%s", sent)

    while True:
        now = datetime.now(timezone.utc)

        try:
            settings = store.get_strategy_settings()
            bias_tf = settings["active_bias_tf"]
            trigger_tf = settings["active_trigger_tf"]

            combo = (bias_tf, trigger_tf)
            if active_combo_seen is not None and combo != active_combo_seen:
                logger.info("timeframe combo changed %s -> %s (mode=%s) — resetting close marker",
                            active_combo_seen, combo, settings["mode"])
                last_trigger_open_seen = None
            active_combo_seen = combo

            candles_trigger = fetch_candles(
                cfg["data"]["coin"], trigger_tf,
                _ms(now) - lookback_ms(trigger_tf), _ms(now),
            )
            if candles_trigger:
                last_data_timestamp = datetime.fromtimestamp(
                    candles_trigger[-1].close_time_ms / 1000, tz=timezone.utc
                )

            newest_open = newest_closed_open_time(candles_trigger)
            new_trigger_close = newest_open is not None and newest_open != last_trigger_open_seen

            if new_trigger_close:
                last_trigger_open_seen = newest_open
                candles_bias = fetch_candles(
                    cfg["data"]["coin"], bias_tf,
                    _ms(now) - lookback_ms(bias_tf), _ms(now),
                )
                if candles_bias:
                    bias_result = compute_bias(
                        candles_bias,
                        fractal_width=cfg["strategy"]["fractal_width"],
                        sr_lookback=cfg["strategy"]["sr_lookback"],
                    )
                    current_bias_label = bias_result.bias.value
                    # Publish structural levels for the manual trade panel
                    levels = manual_entry_levels(bias_result, candles_trigger[-1].close)
                    store.record_market_state(
                        last_price=candles_trigger[-1].close, bias=current_bias_label, **levels,
                    )
                    latest_levels = levels
                    latest_price = candles_trigger[-1].close

                    ind_cfg = store.get_indicator_config()
                    result, readings = evaluate_signal(
                        candles_bias, candles_trigger, now=now,
                        config=ind_cfg, ichimoku_variant=ind_cfg["ichimoku_variant"],
                        return_readings=True,
                    )
                    latest_indicators = {
                        "mode": settings["mode"], "bias_tf": bias_tf, "trigger_tf": trigger_tf,
                        "readings": readings,
                    }

                    # Edge-trigger: with state-based configs (e.g. Fisher
                    # disabled) alignment persists across bars — only the
                    # TRANSITION into alignment is a signal event. With
                    # Fisher enabled its cross-bar-only vote makes this a
                    # no-op (alignment can't persist), preserving the
                    # original behavior exactly.
                    enabled_votes = [r["vote"] for n, r in readings.items() if r["enabled"]]
                    alignment = (enabled_votes[0] if enabled_votes
                                 and all(v == enabled_votes[0] for v in enabled_votes)
                                 and enabled_votes[0] != "NONE" else None)
                    is_new_alignment = alignment is not None and alignment != prev_alignment
                    prev_alignment = alignment

                    if isinstance(result, Signal) and is_new_alignment:
                        _handle_signal(result, cfg, store, execution, telegram, ledger,
                                       breaker, peak_equity, latest_indicators, settings)
                    elif isinstance(result, SuppressedSignal) and is_new_alignment:
                        logger.info("Signal suppressed: %s", result.reason)

            if candles_trigger:
                current_price = candles_trigger[-1].close
                latest_price = current_price
                for closed_pos in ledger.check_exits(current_price, now=now):
                    telegram.send(decorate(
                        format_exit_alert(closed_pos, ledger.daily_pnl(),
                                          context=alert_context(settings=settings)), settings))
                    logger.info("Paper exit: %s %.2fR", closed_pos.exit_reason, closed_pos.pnl_r)

                peak_equity = max(peak_equity, ledger.equity)
                breaker.update(ledger.current_equity())
                if breaker.just_tripped():
                    halt_events_today += 1
                    telegram.send(decorate(
                        format_halt_alert(ledger.daily_pnl_pct(),
                                          context=alert_context(settings=settings)), settings))
                    store.record_risk_event("circuit_breaker_trip", {
                        "daily_pnl_pct": ledger.daily_pnl_pct(), "equity": ledger.equity,
                    })
                    logger.warning("Circuit breaker tripped: %s", breaker.halt_reason)

                store.record_telemetry(
                    equity=ledger.equity, day_start_equity=ledger.day_start_equity,
                    engine_state=store.get_engine_state(),
                )

            logger.info(
                "alive: state=%s mode=%s tf=%s/%s bias=%s equity=%.2f open=%d daily_pnl=%.2f cb_halted=%s",
                store.get_engine_state(), settings["mode"], bias_tf, trigger_tf,
                current_bias_label, ledger.equity, len(ledger.open_positions),
                ledger.daily_pnl(), breaker.is_halted(),
            )

        except Exception:
            feed_errors_since_heartbeat += 1
            logger.warning("Error during evaluation loop", exc_info=True)

        if now.date() > last_day:
            telegram.send(decorate(
                format_daily_summary(ledger.today_stats(), current_bias_label, halt_events_today), settings))
            ledger.start_new_day()
            breaker.reset_for_new_day(ledger.equity)
            halt_events_today = 0
            last_day = now.date()
            logger.info("Daily rollover complete; day_start_equity=%.2f", ledger.day_start_equity)

        if (now - last_heartbeat_at) >= timedelta(hours=cfg["telegram"]["heartbeat_interval_hours"]):
            telegram.send(decorate(
                format_heartbeat(current_bias_label, last_data_timestamp, feed_errors_since_heartbeat,
                                 context=alert_context(settings=settings)), settings))
            last_heartbeat_at = now
            feed_errors_since_heartbeat = 0

        time.sleep(POLL_SECONDS)


def _handle_signal(signal: Signal, cfg, store, execution, telegram, ledger,
                   breaker, peak_equity: float, indicators: dict, settings: dict) -> None:
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
        indicators_snapshot=indicators,  # full readings — the backtest-review record
    )
    risk_amount = abs(signal.entry - signal.stop) * decision.quantity
    entry_ctx = {
        "trigger_tf": indicators.get("trigger_tf"), "bias_tf": indicators.get("bias_tf"),
        "readings": indicators.get("readings"),
        "equity": ledger.equity, "day_start_equity": ledger.day_start_equity,
        "open_positions": len(ledger.open_positions),
        "position_line": "none" if not ledger.open_positions
        else f"{len(ledger.open_positions)} open (paper)",
        "attenuation": decision.attenuation_applied,
    }
    alert_text = format_entry_signal(signal, decision.quantity, params["risk_pct"],
                                     risk_amount, context=entry_ctx)

    if not decision.approved:
        telegram.send(decorate(alert_text + "\n⚠️ GATE REJECTED:\n- " + "\n- ".join(decision.reasons), settings),
                      reply_markup=frame_a_markup(signal_id))
        logger.info("Gate rejected signal: %s", decision.reasons)
        return

    if engine_state == "ACTIVE":
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
            telegram.send(decorate(alert_text + f"\n\U0001F916 AUTO-TAKEN (dry_run={result.dry_run}, "
                                                f"attenuation {decision.attenuation_applied:.3f})", settings))
            logger.info("Signal auto-taken (dry_run=%s)", result.dry_run)
        except RuntimeError as exc:
            telegram.send(decorate(alert_text + f"\n\U0001F6D1 BLOCKED BY FLOOR GUARD: {exc}", settings))
            logger.warning("Floor guard blocked auto-take: %s", exc)
        finally:
            execution._intent_sink = None
    else:
        telegram.send(decorate(alert_text + f"\n(engine {engine_state} — manual Take/Skip below)", settings),
                      reply_markup=frame_a_markup(signal_id))
        logger.info("Signal posted for manual take (engine %s)", engine_state)


if __name__ == "__main__":
    run()
