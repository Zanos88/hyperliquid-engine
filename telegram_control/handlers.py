"""Control-plane handlers. All async; all auth-gated; zero trading logic —
handlers translate commands/taps into service calls (store, execution,
risk gate) and report results.

Handlers receive collaborators via a ControlServices container rather
than importing global state, so they are unit-testable with fakes and the
process stays a pure client of the services (module firewall).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from risk.gate import evaluate_gate
from strategy.signals import Signal, SignalDirection
from telegram_control.auth import is_authorized

logger = logging.getLogger(__name__)


@dataclass
class ControlServices:
    store: object       # db.store.TelemetryStore-compatible
    execution: object   # execution.propr_client.ProprExecutionService-compatible
    account_snapshot: Callable[[], dict]
    # returns {"equity", "peak_equity", "day_start_equity", "open_positions_count"}
    gate: Callable = evaluate_gate  # injectable for tests


def frame_b_markup(base: str = "BTC") -> dict:
    """Frame B — position dashboard buttons (V2 report section 4).
    Fractions only, never notional; SL→Breakeven uses Propr's fee-
    inclusive breakEvenPrice field."""
    return {"inline_keyboard": [
        [
            {"text": "Close 25%", "callback_data": f"close_25_{base}"},
            {"text": "Close 50%", "callback_data": f"close_50_{base}"},
            {"text": "Close All", "callback_data": f"close_100_{base}"},
        ],
        [
            {"text": "SL → Breakeven", "callback_data": f"slbe_{base}"},
        ],
    ]}


def _user_id(update) -> int | None:
    user = getattr(update, "effective_user", None)
    return getattr(user, "id", None)


def _to_ptb_markup(reply_markup: dict | None):
    """Convert a plain inline-keyboard dict to PTB's InlineKeyboardMarkup
    at the send boundary (markup builders stay plain dicts for tests and
    for the engine's raw-HTTP alert path)."""
    if reply_markup is None:
        return None
    try:
        from telegram import InlineKeyboardMarkup
        return InlineKeyboardMarkup.de_json(reply_markup, None)
    except ImportError:
        return reply_markup  # test environments without PTB semantics


async def _reply(update, text: str, reply_markup: dict | None = None) -> None:
    markup = _to_ptb_markup(reply_markup)
    if getattr(update, "message", None) is not None:
        await update.message.reply_text(text, reply_markup=markup)
    elif getattr(update, "callback_query", None) is not None:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)


def _denied(update, action: str) -> bool:
    uid = _user_id(update)
    if not is_authorized(uid):
        logger.warning("UNAUTHORIZED control attempt: user_id=%s action=%s", uid, action)
        return True
    return False


# ── slash commands (global state) ──

async def cmd_run(update, context, services: ControlServices) -> None:
    if _denied(update, "/run"):
        return
    state = services.store.get_engine_state()
    args = getattr(context, "args", []) or []
    if state == "KILLED" and "confirm" not in args:
        await _reply(update,
                     "\U0001F512 Engine is KILLED (kill switch or guardian flatten).\n"
                     "Reactivating requires explicit confirmation: /run confirm")
        return
    services.store.set_engine_state("ACTIVE", updated_by=f"telegram:{_user_id(update)}")
    await _reply(update, "\U0001F7E2 ACTIVE — automation engine enabled.")


async def cmd_pause(update, context, services: ControlServices) -> None:
    if _denied(update, "/pause"):
        return
    services.store.set_engine_state("PAUSED", updated_by=f"telegram:{_user_id(update)}")
    await _reply(update, "\U0001F534 PAUSED — no new entries; existing positions and brackets stay managed.")


async def cmd_kill(update, context, services: ControlServices) -> None:
    """Prop Saver. Un-blockable: registered with block=False and does no
    waiting on other handlers. Cancels everything, closes everything,
    locks KILLED."""
    if _denied(update, "/kill"):
        return
    result = services.execution.kill_sequence()
    services.store.set_engine_state("KILLED", updated_by=f"telegram:{_user_id(update)}")
    services.store.record_risk_event("kill_invoked", {
        "by": _user_id(update), "dry_run": result.get("dry_run"),
        "cancelled": len(result.get("cancelled_order_ids", [])),
        "closed": len(result.get("closed", [])),
    })
    await _reply(update,
                 "\U0001F6D1 KILL executed.\n"
                 f"Orders cancelled: {len(result.get('cancelled_order_ids', []))} | "
                 f"Positions closed: {len(result.get('closed', []))} | "
                 f"dry_run={result.get('dry_run')}\n"
                 "State locked KILLED — /run confirm to reactivate.")


async def cmd_dashboard(update, context, services: ControlServices) -> None:
    if _denied(update, "/dashboard"):
        return
    snap = services.account_snapshot()
    equity = snap["equity"]
    day_start = snap["day_start_equity"]
    daily_pnl = equity - day_start
    daily_floor = day_start - 3_000
    state = services.store.get_engine_state()

    lines = [
        "\U0001F4CB DASHBOARD",
        f"Engine: {state}",
        f"Equity: ${equity:,.2f}",
        f"Daily P&L: ${daily_pnl:+,.2f} ({daily_pnl / day_start:+.2%})",
        f"Distance to daily floor (${daily_floor:,.0f}): ${equity - daily_floor:,.2f}",
        f"Distance to static floor ($94,000): ${equity - 94_000:,.2f}",
    ]
    try:
        positions = services.execution.get_open_positions()
    except Exception:
        positions = []
        lines.append("(live positions unavailable — showing account snapshot only)")
    for p in positions:
        lines.append(
            f"{p.get('positionSide', '?').upper()} {p.get('quantity')} {p.get('base')} "
            f"@ {p.get('entryPrice')} | mark {p.get('markPrice')} | uPnL {p.get('unrealizedPnl')}"
        )
    if not positions:
        lines.append("Open positions: none")
    lines.append(f"Updated: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    # Frame B attaches whenever there is a position to act on (spec: the
    # position dashboard carries the contextual execution buttons).
    markup = frame_b_markup(positions[0].get("base", "BTC")) if positions else None
    await _reply(update, "\n".join(lines), reply_markup=markup)


async def cmd_risk(update, context, services: ControlServices) -> None:
    if _denied(update, "/risk"):
        return
    args = getattr(context, "args", []) or []
    if not args:
        params = services.store.get_risk_params()
        await _reply(update,
                     "⚙️ RISK PARAMS\n"
                     f"risk_pct: {params['risk_pct']:.4f} ({params['risk_pct']:.2%}) [bounds 0.25%-1.0%]\n"
                     f"alpha: {params['alpha']}\n"
                     f"max_concurrent: {params['max_concurrent']}\n"
                     "Set with: /risk pct 0.5 | /risk alpha 1.5 | /risk max 2")
        return

    name_map = {"pct": "risk_pct", "alpha": "alpha", "max": "max_concurrent"}
    if len(args) != 2 or args[0] not in name_map:
        await _reply(update, "Usage: /risk [pct <0.25-1.0> | alpha <>=1.0> | max <n>]")
        return
    param = name_map[args[0]]
    try:
        value = float(args[1]) / 100 if param == "risk_pct" else float(args[1])
        if param == "max_concurrent":
            value = int(value)
        new = services.store.set_risk_param(param, value, updated_by=f"telegram:{_user_id(update)}")
        await _reply(update, f"✅ {param} updated -> {new[param]} (change logged)")
    except Exception as exc:
        await _reply(update, f"❌ rejected: {exc}")


def _safe_positions(services: ControlServices, base: str) -> list[dict]:
    """Position lookup that survives the no-active-account state (pre-
    purchase / dry-run) — found by live Frame B testing: the raw SDK call
    raises `account_id not set` with no active challenge attempt."""
    try:
        return services.execution.get_open_positions(base=base)
    except Exception:
        logger.warning("position lookup failed (no active trading account?)", exc_info=True)
        return []


# ── inline buttons (contextual execution — every path through the gate) ──

async def cb_take_signal(update, context, services: ControlServices) -> None:
    """callback_data: take_<riskpct>_<signal_id>  e.g. take_0.75_01ABC..."""
    if _denied(update, "take"):
        return
    _, pct_str, signal_id = update.callback_query.data.split("_", 2)
    risk_pct = float(pct_str) / 100

    pending = services.store.get_pending_signal(signal_id)
    if pending is None or pending["status"] != "pending":
        await _reply(update, "⚠️ Signal expired or already resolved.")
        return

    snap = services.account_snapshot()
    signal = Signal(
        direction=SignalDirection[pending["direction"]],
        entry=pending["entry"], stop=pending["stop"], target=pending["target"],
        reward_risk=pending["reward_risk"], timestamp=datetime.now(timezone.utc),
        bias_reason="manual take", trigger_reason="frame A",
    )
    params = services.store.get_risk_params()
    decision = services.gate(
        services.store.get_engine_state(), signal,
        equity=snap["equity"], peak_equity=snap["peak_equity"],
        day_start_equity=snap["day_start_equity"],
        open_positions_count=snap["open_positions_count"],
        risk_pct=risk_pct, alpha=params["alpha"], max_concurrent=params["max_concurrent"],
    )
    if not decision.approved:
        await _reply(update, "❌ Gate rejected:\n- " + "\n- ".join(decision.reasons))
        return

    result = services.execution.create_entry_with_bracket(
        direction=pending["direction"].lower(),
        quantity=str(decision.quantity),
        stop_trigger=str(pending["stop"]),
        target_trigger=str(pending["target"]),
        entry_ref_price=str(pending["entry"]),
    )
    services.store.resolve_pending_signal(signal_id, "taken", resolved_by=f"telegram:{_user_id(update)}")
    await _reply(update,
                 f"✅ TAKEN @ {risk_pct:.2%} risk (dry_run={result.dry_run})\n"
                 f"qty {decision.quantity} | risk ${decision.risk_usd:,.2f} | "
                 f"attenuation {decision.attenuation_applied:.3f}")


async def cb_skip_signal(update, context, services: ControlServices) -> None:
    if _denied(update, "skip"):
        return
    _, signal_id = update.callback_query.data.split("_", 1)
    services.store.resolve_pending_signal(signal_id, "skipped", resolved_by=f"telegram:{_user_id(update)}")
    await _reply(update, "⏭️ Signal skipped.")


async def cb_close_fraction(update, context, services: ControlServices) -> None:
    """callback_data: close_<25|50|100>_BTC — risk-reducing, gate not
    required (the gate guards entries; closes always reduce exposure)."""
    if _denied(update, "close"):
        return
    _, pct_str, base = update.callback_query.data.split("_", 2)
    fraction = Decimal(pct_str) / Decimal(100)

    positions = _safe_positions(services, base)
    if not positions:
        await _reply(update, f"No open {base} position (or no active trading account).")
        return
    result = services.execution.close_position_market(positions[0], fraction=fraction, purpose=f"close_{pct_str}")
    await _reply(update, f"✂️ Close {pct_str}% dispatched (dry_run={result.dry_run}).")


async def cb_sl_breakeven(update, context, services: ControlServices) -> None:
    """callback_data: slbe_BTC — move SL to the position's breakEvenPrice
    (fee-inclusive, verified field in api.md; better than raw entry)."""
    if _denied(update, "slbe"):
        return
    _, base = update.callback_query.data.split("_", 1)
    positions = _safe_positions(services, base)
    if not positions:
        await _reply(update, f"No open {base} position (or no active trading account).")
        return
    pos = positions[0]
    be = pos.get("breakEvenPrice")
    if not be:
        await _reply(update, "⚠️ breakEvenPrice missing on position — flagged; SL unchanged. "
                             "(Open item: verify field at first live position.)")
        return
    result = services.execution.move_stop_to(pos, trigger_price=str(be))
    await _reply(update, f"\U0001F512 SL -> breakeven {be} (dry_run={result.dry_run}).")
