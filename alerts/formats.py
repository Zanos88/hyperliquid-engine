"""Structured alert templates — decision-support format (redesigned
2026-07-07 after test-mode feedback). Standalone: no imports from any
other repo; strategy/risk/ledger never import this module.

Every alert answers: WHAT action (explicit BUY/SELL, never inferred from
a bias label), WHY it fired (per-indicator readings — the same data
logged to indicators_snapshot, surfaced not recomputed), POSITION
CONTEXT, and RISK (structural stop/target, R:R from actual math, floor
distances). Execution venue is Propr; no venue names appear in alerts.

All formatters accept an optional `context` dict assembled by the engine
from state it already holds:
    trigger_tf, bias_tf, readings, equity, day_start_equity,
    open_positions, position_line, attenuation, last_price,
    levels {long_stop, long_target, short_stop, short_target}
Missing context degrades gracefully (sections are omitted, never faked).
"""
from __future__ import annotations

from datetime import datetime

from ledger.tracker import ClosedPosition
from strategy.signals import Signal, SignalDirection

STATIC_FLOOR_USD = 94_000.0
DAILY_LOSS_LIMIT_USD = 3_000.0

_TF_LABEL = {"bias_sr": "bias", "ichimoku": "bias", "fisher": "trigger",
             "obv": "trigger", "rsi": "trigger"}


def _floor_lines(context: dict) -> list[str]:
    equity = context.get("equity")
    day_start = context.get("day_start_equity")
    if equity is None or day_start is None:
        return []
    daily_floor = day_start - DAILY_LOSS_LIMIT_USD
    return [
        f"Floors: daily ${daily_floor:,.0f} (${equity - daily_floor:,.0f} away) | "
        f"static ${STATIC_FLOOR_USD:,.0f} (${equity - STATIC_FLOOR_USD:,.0f} away)"
    ]


def _reasoning_lines(context: dict) -> list[str]:
    """One bullet per ENABLED indicator with its actual reading — surfaces
    the exact rule that fired, from the same dict stored in
    indicators_snapshot."""
    readings = context.get("readings") or {}
    if not readings:
        return []
    bias_tf = context.get("bias_tf", "?")
    trigger_tf = context.get("trigger_tf", "?")
    lines: list[str] = []
    off: list[str] = []
    for name, r in readings.items():
        if not r.get("enabled"):
            off.append(name)
            continue
        tf = bias_tf if _TF_LABEL.get(name) == "bias" else trigger_tf
        if name == "bias_sr":
            lines.append(f"• Bias ({tf}): {r.get('bias')} — {r.get('reason')}")
        elif name == "fisher":
            val = r.get("value")
            val_s = f" (value {val:.2f})" if isinstance(val, (int, float)) else ""
            lines.append(f"• Fisher ({tf}): {r.get('cross')} cross{val_s}")
        elif name == "obv":
            lines.append(f"• OBV ({tf}): {r.get('state')} (vs its 20-SMA)")
        elif name == "rsi":
            val = r.get("value")
            side = ">50 bullish" if r.get("vote") == "LONG" else "<50 bearish" if r.get("vote") == "SHORT" else "at 50"
            val_s = f"{val:.1f} " if isinstance(val, (int, float)) else ""
            lines.append(f"• RSI ({tf}): {val_s}{side}")
        elif name == "ichimoku":
            t, k = r.get("tenkan"), r.get("kijun")
            tk = f" (tenkan {t:,.0f} / kijun {k:,.0f})" if isinstance(t, (int, float)) and isinstance(k, (int, float)) else ""
            lines.append(f"• Ichimoku ({tf}, {r.get('variant', 'standard')}): {r.get('vote')} — price vs Kumo + TK cross{tk}")
    if off:
        lines.append("• Off: " + ", ".join(off))
    return lines


def _position_context_lines(context: dict) -> list[str]:
    lines = []
    pos = context.get("position_line")
    if pos is not None:
        lines.append(f"Current position: {pos}")
    equity = context.get("equity")
    day_start = context.get("day_start_equity")
    if equity is not None and day_start is not None:
        lines.append(f"Equity ${equity:,.2f} | day P&L ${equity - day_start:+,.2f}")
    return lines


def format_entry_signal(signal: Signal, quantity: float, risk_pct: float,
                        risk_amount: float, context: dict | None = None) -> str:
    context = context or {}
    is_long = signal.direction == SignalDirection.LONG
    action = "BUY" if is_long else "SELL"
    side = "LONG" if is_long else "SHORT"
    trigger_tf = context.get("trigger_tf", "trigger")

    lines = [
        f"\U0001F3AF SIGNAL — {action} BTC-PERP ({side})",
        "── Direction",
        f"{action} {side.lower()} @ ~${signal.entry:,.2f} (market entry on {trigger_tf} close)",
    ]
    reasoning = _reasoning_lines(context)
    if reasoning:
        lines.append("── Reasoning (why this fired)")
        lines.extend(reasoning)
    pos_ctx = _position_context_lines(context)
    if pos_ctx:
        lines.append("── Position Context")
        lines.extend(pos_ctx)
    lines.append("── Risk")
    lines.append(f"Stop ${signal.stop:,.2f} (structural: beyond nearest S/R −0.15%) | "
                 f"Target ${signal.target:,.2f} (next opposing structural level)")
    att = context.get("attenuation")
    att_s = f", attenuation {att:.3f}" if isinstance(att, (int, float)) else ""
    lines.append(f"R:R {signal.reward_risk:.2f} | Size {quantity:.5f} BTC | "
                 f"Risk ${risk_amount:,.2f} ({risk_pct:.2%}{att_s})")
    lines.extend(_floor_lines(context))
    lines.append(f"Time: {signal.timestamp.strftime('%H:%M UTC')}")
    return "\n".join(lines)


def format_exit_alert(closed: ClosedPosition, running_daily_pnl: float,
                      context: dict | None = None) -> str:
    context = context or {}
    was_long = closed.signal.direction == SignalDirection.LONG
    closing_action = "SELL" if was_long else "BUY"
    side = "LONG" if was_long else "SHORT"
    won = closed.pnl > 0
    emoji = "✅" if won else "❌"
    outcome = "TARGET HIT" if closed.exit_reason == "target" else "STOP HIT"

    lines = [
        f"{emoji} CLOSED {side} ({closing_action}) — {outcome}",
        f"Entry ${closed.signal.entry:,.2f} → Exit ${closed.exit_price:,.2f} "
        f"({closed.quantity:.5f} BTC)",
        f"Result: {closed.pnl_r:+.2f}R (${closed.pnl:+,.2f})",
        f"Running daily P&L: ${running_daily_pnl:+,.2f}",
    ]
    open_n = context.get("open_positions")
    if open_n is not None:
        lines.append(f"Remaining open positions: {open_n}")
    lines.extend(_floor_lines(context))
    lines.append(f"Time: {closed.closed_at.strftime('%H:%M UTC')}")
    return "\n".join(lines)


def format_daily_summary(stats: dict, current_bias: str, halt_events_today: int,
                         context: dict | None = None) -> str:
    context = context or {}
    win_rate = stats["win_rate"]
    win_rate_str = f"{win_rate:.0%}" if win_rate is not None else "n/a"
    day_start = stats["equity"] - stats["daily_pnl"]
    lines = [
        "\U0001F4CA DAILY SUMMARY (00:00 UTC)",
        f"Signals fired: {stats['signals_fired']} | Closed: {stats['closed_trades']} | Win rate: {win_rate_str}",
        f"Equity: ${day_start:,.2f} → ${stats['equity']:,.2f} "
        f"(${stats['daily_pnl']:+,.2f}, {stats['daily_pnl_pct']:+.2%})",
        f"Circuit-breaker halts today: {halt_events_today}",
        f"Current bias: {current_bias}",
    ]
    lines.extend(_floor_lines({"equity": stats["equity"],
                               "day_start_equity": stats["equity"]}))  # new day baseline = current equity
    return "\n".join(lines)


def format_heartbeat(current_bias: str, last_data_timestamp: datetime,
                     feed_errors_since_last: int, context: dict | None = None) -> str:
    """WHY-state snapshot, not just 'alive': levels, indicator readings,
    floor distances — a dead process is noticed by silence; a drifting
    strategy is noticed by this content."""
    context = context or {}
    status = "\U0001F7E2 alive" if feed_errors_since_last == 0 else "\U0001F7E1 alive (with feed errors)"
    lines = [f"\U0001F493 HEARTBEAT: {status}",
             f"Bias: {current_bias}"]

    last_price = context.get("last_price")
    levels = context.get("levels") or {}
    if last_price is not None:
        lines.append(f"Last price: ${last_price:,.2f}")
    ls, lt = levels.get("long_stop"), levels.get("long_target")
    if ls and lt and last_price:
        rr = (lt - last_price) / max(last_price - ls, 1e-9)
        lines.append(f"Structural long setup: stop ${ls:,.0f} / target ${lt:,.0f} (R:R {rr:.1f})")
    ss, st = levels.get("short_stop"), levels.get("short_target")
    if ss and st and last_price:
        rr = (last_price - st) / max(ss - last_price, 1e-9)
        lines.append(f"Structural short setup: stop ${ss:,.0f} / target ${st:,.0f} (R:R {rr:.1f})")

    reasoning = _reasoning_lines(context)
    if reasoning:
        lines.append("Last readings:")
        lines.extend(reasoning)

    pos = context.get("position_line")
    if pos is not None:
        lines.append(f"Position: {pos}")
    lines.extend(_floor_lines(context))
    lines.append(f"Last data: {last_data_timestamp.strftime('%Y-%m-%d %H:%M UTC')} | "
                 f"feed errors since last heartbeat: {feed_errors_since_last}")
    return "\n".join(lines)


def format_halt_alert(daily_pnl_pct: float, context: dict | None = None) -> str:
    context = context or {}
    lines = [
        "\U0001F6D1 CIRCUIT BREAKER HALT",
        f"Daily P&L reached {daily_pnl_pct:+.2%}, breaching the -2.5% internal buffer "
        "(inside the challenge's real -3% daily limit).",
    ]
    equity = context.get("equity")
    day_start = context.get("day_start_equity")
    if equity is not None and day_start is not None:
        lines.append(f"Equity ${equity:,.2f} | day P&L ${equity - day_start:+,.2f}")
    open_n = context.get("open_positions")
    if open_n is not None:
        lines.append(f"Open positions: {open_n} (existing brackets stay managed)")
    lines.extend(_floor_lines(context))
    lines.append("New signal generation halted until the next 00:00 UTC rollover.")
    return "\n".join(lines)
