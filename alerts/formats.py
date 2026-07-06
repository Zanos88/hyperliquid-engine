"""Alert message templates. Standalone — no imports from any other repo.

Written standalone per explicit user instruction: not imported from or
copied out of Bullphoric's alert code; the emoji-header / labeled-field
layout is the generic shape the build spec's section 8 example uses.

OPEN ITEM (build spec 3.5 / section 8): these formats are implemented per
the spec's example but are PENDING FINAL USER APPROVAL before being
considered locked.
"""
from __future__ import annotations

from datetime import datetime

from ledger.tracker import ClosedPosition
from strategy.signals import Signal, SignalDirection


def format_entry_signal(signal: Signal, quantity: float, risk_pct: float, risk_amount: float) -> str:
    direction_label = "LONG" if signal.direction == SignalDirection.LONG else "SHORT"
    return (
        f"\U0001F3AF BTC-PERP {direction_label} SIGNAL\n"
        f"4H Bias: {signal.bias_reason}\n"
        f"1H Trigger: {signal.trigger_reason}\n"
        f"Entry: ${signal.entry:,.2f} | Stop: ${signal.stop:,.2f} | "
        f"Target: ${signal.target:,.2f} (R:R {signal.reward_risk:.1f})\n"
        f"Size: {quantity:.5f} BTC (${risk_amount:,.2f} risk, {risk_pct:.2%})\n"
        f"Time: {signal.timestamp.strftime('%H:%M UTC')}"
    )


def format_exit_alert(closed: ClosedPosition, running_daily_pnl: float) -> str:
    emoji = "✅" if closed.pnl > 0 else "❌"
    direction_label = "LONG" if closed.signal.direction == SignalDirection.LONG else "SHORT"
    return (
        f"{emoji} BTC-PERP {direction_label} EXIT ({closed.exit_reason.upper()})\n"
        f"Entry: ${closed.signal.entry:,.2f} -> Exit: ${closed.exit_price:,.2f}\n"
        f"Result: {closed.pnl_r:+.2f}R (${closed.pnl:+,.2f})\n"
        f"Running daily P&L: ${running_daily_pnl:+,.2f}\n"
        f"Time: {closed.closed_at.strftime('%H:%M UTC')}"
    )


def format_daily_summary(stats: dict, current_bias: str, halt_events_today: int) -> str:
    win_rate = stats["win_rate"]
    win_rate_str = f"{win_rate:.0%}" if win_rate is not None else "n/a"
    return (
        "\U0001F4CA DAILY SUMMARY (00:00 UTC)\n"
        f"Signals fired: {stats['signals_fired']}\n"
        f"Closed trades: {stats['closed_trades']} | Win rate: {win_rate_str}\n"
        f"Daily P&L: ${stats['daily_pnl']:+,.2f} ({stats['daily_pnl_pct']:+.2%})\n"
        f"Circuit-breaker halts today: {halt_events_today}\n"
        f"Current 4H bias: {current_bias}\n"
        f"Equity: ${stats['equity']:,.2f}"
    )


def format_heartbeat(current_bias: str, last_data_timestamp: datetime, feed_errors_since_last: int) -> str:
    status = "\U0001F7E2 alive" if feed_errors_since_last == 0 else "\U0001F7E1 alive (with feed errors)"
    return (
        f"\U0001F493 HEARTBEAT: {status}\n"
        f"Current 4H bias: {current_bias}\n"
        f"Last data timestamp: {last_data_timestamp.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Feed errors since last heartbeat: {feed_errors_since_last}"
    )


def format_halt_alert(daily_pnl_pct: float) -> str:
    return (
        "\U0001F6D1 CIRCUIT BREAKER HALT\n"
        f"Daily P&L reached {daily_pnl_pct:+.2%}, breaching the -2.5% internal buffer.\n"
        "New signal generation is halted until the next 00:00 UTC rollover.\n"
        "No orders were placed — this bot is signal-only (Stage 1)."
    )
