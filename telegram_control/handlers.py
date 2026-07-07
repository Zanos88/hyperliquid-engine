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


async def _ack(update) -> None:
    """Acknowledge a callback IMMEDIATELY (before any DB work). Telegram
    expires unanswered callback queries within seconds — slow store paths
    were blowing that window ('Query is too old'). Stale/duplicate answers
    are tolerated: the message edit still lands."""
    cq = getattr(update, "callback_query", None)
    if cq is None:
        return
    try:
        await cq.answer()
    except Exception:
        logger.debug("callback ack failed (stale/duplicate) — continuing with edit")


async def _reply(update, text: str, reply_markup: dict | None = None) -> None:
    markup = _to_ptb_markup(reply_markup)
    if getattr(update, "message", None) is not None:
        await update.message.reply_text(text, reply_markup=markup)
    elif getattr(update, "callback_query", None) is not None:
        await _ack(update)
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
    try:
        s = services.store.get_strategy_settings()
        mode_line = f"Mode: {s['mode']} | TF: {s['active_bias_tf']} bias / {s['active_trigger_tf']} trigger"
    except Exception:
        mode_line = "Mode: (settings unavailable)"
    ind_line = _indicator_summary_safe(services.store)
    try:
        ms = services.store.get_market_state()
        levels_line = (f"Bias: {ms['bias']} | last ${ms['last_price']:,.2f} | "
                       f"long stop/target: "
                       f"{'$%s / $%s' % (format(ms['long_stop'], ',.0f'), format(ms['long_target'], ',.0f')) if ms['long_stop'] and ms['long_target'] else 'no valid structure'}"
                       ) if ms else None
    except Exception:
        levels_line = None

    lines = [
        "\U0001F4CB DASHBOARD",
        f"Engine: {state}",
        mode_line,
        *( [ind_line] if ind_line else [] ),
        *( [levels_line] if levels_line else [] ),
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
        summary = _indicator_summary_safe(services.store)
        await _reply(update,
                     "⚙️ RISK PARAMS\n"
                     f"risk_pct: {params['risk_pct']:.4f} ({params['risk_pct']:.2%}) [bounds 0.25%-1.0%]\n"
                     f"alpha: {params['alpha']}\n"
                     f"max_concurrent: {params['max_concurrent']}\n"
                     + (summary + "\n" if summary else "")
                     + "Set with: /risk pct 0.5 | /risk alpha 1.5 | /risk max 2")
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


# ── /settings — Trojan-style mode + timeframe panel ──

_TF_MENUS = {
    # menu key -> (setting name, allowed list source, panel title)
    "pbias": ("prod_bias_tf", "production", "Production BIAS timeframe"),
    "ptrig": ("prod_trigger_tf", "production", "Production TRIGGER timeframe"),
    "tbias": ("test_bias_tf", "test", "Test BIAS timeframe"),
    "ttrig": ("test_trigger_tf", "test", "Test TRIGGER timeframe"),
}


INDICATOR_LABELS = {"bias_sr": "Bias (S/R+Fib)", "fisher": "Fisher", "obv": "OBV",
                    "rsi": "RSI", "ichimoku": "Ichimoku"}


def indicator_summary(cfg: dict) -> str:
    """'Active: Bias+Fisher+OBV (RSI, Ichimoku off)' style readout."""
    on = [INDICATOR_LABELS[n] for n in INDICATOR_LABELS if cfg.get(n)]
    off = [INDICATOR_LABELS[n] for n in INDICATOR_LABELS if not cfg.get(n)]
    line = "Active: " + "+".join(on) if on else "Active: NONE"
    if off:
        line += " (" + ", ".join(off) + " off)"
    if cfg.get("ichimoku"):
        line += f" | Ichimoku: {cfg.get('ichimoku_variant', 'standard')}"
    return line


def _indicator_summary_safe(store) -> str | None:
    getter = getattr(store, "get_indicator_config", None)
    if not callable(getter):
        return None
    try:
        return indicator_summary(getter())
    except Exception:
        return None


def _settings_text(s: dict, store=None) -> str:
    mode_icon = "\U0001F3ED" if s["mode"] == "production" else "\U0001F9EA"
    text = (
        "⚙️ STRATEGY SETTINGS\n"
        f"Mode: {mode_icon} {s['mode'].upper()}\n"
        f"Production combo: {s['prod_bias_tf']} bias / {s['prod_trigger_tf']} trigger\n"
        f"Test combo: {s['test_bias_tf']} bias / {s['test_trigger_tf']} trigger\n"
        f"Active: {s['active_bias_tf']} / {s['active_trigger_tf']}"
    )
    summary = _indicator_summary_safe(store) if store is not None else None
    if summary:
        text += "\n" + summary
    return text + "\nChanges apply from the next engine cycle."


def indicators_menu_markup(cfg: dict) -> dict:
    rows = []
    for name, label in INDICATOR_LABELS.items():
        mark = "✅" if cfg.get(name) else "❌"
        rows.append([{"text": f"{mark} {label}", "callback_data": f"stg_ind_{name}"}])
    other = "crypto" if cfg.get("ichimoku_variant") == "standard" else "standard"
    rows.append([{"text": f"Ichimoku variant: {cfg.get('ichimoku_variant', 'standard')} "
                          f"(tap for {other})", "callback_data": f"stg_indvar_{other}"}])
    rows.append([{"text": "⬅️ Back", "callback_data": "stg_back"}])
    return {"inline_keyboard": rows}


def settings_menu_markup(s: dict) -> dict:
    prod_mark = " ✓" if s["mode"] == "production" else ""
    test_mark = " ✓" if s["mode"] == "test" else ""
    return {"inline_keyboard": [
        [
            {"text": f"\U0001F3ED Production Mode{prod_mark}", "callback_data": "stg_mode_production"},
            {"text": f"\U0001F9EA Test Mode{test_mark}", "callback_data": "stg_mode_test"},
        ],
        [
            {"text": "Prod Bias TF", "callback_data": "stg_menu_pbias"},
            {"text": "Prod Trigger TF", "callback_data": "stg_menu_ptrig"},
        ],
        [
            {"text": "Test Bias TF", "callback_data": "stg_menu_tbias"},
            {"text": "Test Trigger TF", "callback_data": "stg_menu_ttrig"},
        ],
        [{"text": "\U0001F4C8 Indicators", "callback_data": "stg_menu_ind"}],
    ]}


def timeframe_menu_markup(menu_key: str, current: str) -> dict:
    from strategy.timeframes import PRODUCTION_TIMEFRAMES, TEST_TIMEFRAMES

    _, mode_kind, _ = _TF_MENUS[menu_key]
    options = PRODUCTION_TIMEFRAMES if mode_kind == "production" else TEST_TIMEFRAMES
    rows, row = [], []
    for tf in options:
        mark = " ✓" if tf == current else ""
        row.append({"text": f"{tf}{mark}", "callback_data": f"stg_{menu_key}_{tf}"})
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": "⬅️ Back", "callback_data": "stg_back"}])
    return {"inline_keyboard": rows}


async def cmd_settings(update, context, services: ControlServices) -> None:
    if _denied(update, "/settings"):
        return
    s = services.store.get_strategy_settings()
    await _reply(update, _settings_text(s, services.store), reply_markup=settings_menu_markup(s))


async def cb_settings(update, context, services: ControlServices) -> None:
    """All stg_* callbacks: mode switches, submenu opens, timeframe picks."""
    if _denied(update, "settings"):
        return
    await _ack(update)  # ack before any DB round-trips
    data = update.callback_query.data  # stg_...
    who = f"telegram:{_user_id(update)}"
    parts = data.split("_", 2)  # ["stg", verb, rest]
    verb = parts[1] if len(parts) > 1 else ""
    rest = parts[2] if len(parts) > 2 else ""

    try:
        if verb == "mode":
            s = services.store.set_strategy_setting("mode", rest, updated_by=who)
        elif verb == "menu" and rest == "ind":
            cfg = services.store.get_indicator_config()
            await _reply(update, "\U0001F4C8 CONFLUENCE INDICATORS — tap to toggle\n"
                                 + indicator_summary(cfg),
                         reply_markup=indicators_menu_markup(cfg))
            return
        elif verb == "menu":
            s = services.store.get_strategy_settings()
            setting_name, _, title = _TF_MENUS[rest]
            await _reply(update, f"⚙️ {title}\nCurrent: {s[setting_name]}",
                         reply_markup=timeframe_menu_markup(rest, s[setting_name]))
            return
        elif verb == "ind":
            cfg = services.store.get_indicator_config()
            new_cfg = services.store.set_indicator_toggle(rest, not cfg[rest], updated_by=who)
            await _reply(update, "\U0001F4C8 CONFLUENCE INDICATORS — tap to toggle\n"
                                 + indicator_summary(new_cfg),
                         reply_markup=indicators_menu_markup(new_cfg))
            return
        elif verb == "indvar":
            new_cfg = services.store.set_ichimoku_variant(rest, updated_by=who)
            await _reply(update, "\U0001F4C8 CONFLUENCE INDICATORS — tap to toggle\n"
                                 + indicator_summary(new_cfg),
                         reply_markup=indicators_menu_markup(new_cfg))
            return
        elif verb == "back":
            s = services.store.get_strategy_settings()
        elif verb in _TF_MENUS:
            setting_name, _, _ = _TF_MENUS[verb]
            s = services.store.set_strategy_setting(setting_name, rest, updated_by=who)
        else:
            await _reply(update, f"Unknown settings action: {data}")
            return
    except ValueError as exc:
        # invalid change (combo/toggle rule) — explain, re-show panel
        s = services.store.get_strategy_settings()
        await _reply(update, f"❌ {exc}\n\n{_settings_text(s, services.store)}",
                     reply_markup=settings_menu_markup(s))
        return

    await _reply(update, _settings_text(s, services.store), reply_markup=settings_menu_markup(s))


async def cmd_testalert(update, context, services: ControlServices) -> None:
    """Render synthetic entry + exit alerts through the REAL formatters so
    formats can be reviewed without waiting for live confluence. Clearly
    labeled; no ledger/DB writes; nothing dispatched."""
    if _denied(update, "/testalert"):
        return
    from datetime import datetime, timezone

    from alerts.formats import format_entry_signal, format_exit_alert
    from ledger.tracker import ClosedPosition

    sample_readings = {
        "bias_sr": {"enabled": True, "vote": "LONG", "bias": "BULLISH",
                    "reason": "price 61,780.00 above 0.618 retrace 61,320.00 and holding support"},
        "fisher": {"enabled": True, "vote": "LONG", "cross": "bullish", "value": 1.24},
        "obv": {"enabled": True, "vote": "LONG", "state": "rising", "value": 15234.5},
        "rsi": {"enabled": False, "vote": "LONG", "value": 57.3},
        "ichimoku": {"enabled": False, "vote": "NONE", "tenkan": 61650.0, "kijun": 61400.0,
                     "senkou_a": 61200.0, "senkou_b": 60900.0, "variant": "standard"},
    }
    ctx = {"trigger_tf": "1h", "bias_tf": "4h", "readings": sample_readings,
           "equity": 100_000.0, "day_start_equity": 100_000.0,
           "open_positions": 0, "position_line": "none", "attenuation": 1.0}
    now = datetime.now(timezone.utc)
    sig = Signal(direction=SignalDirection.LONG, entry=61_780.0, stop=60_900.0,
                 target=63_600.0, reward_risk=(63_600 - 61_780) / (61_780 - 60_900),
                 timestamp=now, bias_reason=sample_readings["bias_sr"]["reason"],
                 trigger_reason="confluence: bias_sr:LONG + fisher:LONG + obv:LONG")
    entry_text = format_entry_signal(sig, 0.85227, 0.0075, 750.0, context=ctx)

    closed = ClosedPosition(signal=sig, quantity=0.85227, opened_at=now, closed_at=now,
                            exit_price=63_600.0, exit_reason="target",
                            pnl=1_551.13, pnl_r=2.07)
    exit_text = format_exit_alert(closed, 1_551.13,
                                  context={**ctx, "equity": 101_551.13})

    banner = "⚠️ SYNTHETIC — format preview only, not a real signal\n\n"
    await _reply(update, banner + entry_text)
    if getattr(update, "message", None) is not None:
        await update.message.reply_text(banner + exit_text)


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
    await _ack(update)
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
    await _ack(update)
    _, signal_id = update.callback_query.data.split("_", 1)
    services.store.resolve_pending_signal(signal_id, "skipped", resolved_by=f"telegram:{_user_id(update)}")
    await _reply(update, "⏭️ Signal skipped.")


async def cb_close_fraction(update, context, services: ControlServices) -> None:
    """callback_data: close_<25|50|100>_BTC — risk-reducing, gate not
    required (the gate guards entries; closes always reduce exposure)."""
    if _denied(update, "close"):
        return
    await _ack(update)
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
    await _ack(update)
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
