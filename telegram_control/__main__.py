"""Control-plane entrypoint: python -m telegram_control

Runs the python-telegram-bot v20+ application (long polling) as its own
OS process, wired to the shared Postgres store and a dry-run-governed
execution service. /kill is registered with block=False so no other
handler can queue-block it.
"""
from __future__ import annotations

import functools
import logging
import os

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("telegram_control")

# httpx logs full request URLs at INFO — which for the Telegram Bot API
# includes the bot token. Silence to WARNING so the token never lands in
# persisted logs (Railway retains stdout).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_account_snapshot(store, execution):
    """Live account snapshot with telemetry fallback (pre-purchase / dry-run)."""
    def snapshot() -> dict:
        try:
            acct = execution.get_account()
            data = acct.get("data", acct)
            balance = float(data["balance"])
            upnl = float(data.get("totalUnrealizedPnl") or 0)
            iso = float(data.get("isolatedPositionMargin") or 0)
            equity = balance + upnl + iso
            peak = float(data.get("highWaterMark") or equity)
            positions = execution.get_open_positions()
            return {"equity": equity, "peak_equity": max(peak, equity),
                    "day_start_equity": equity,  # engine telemetry refines this
                    "open_positions_count": len(positions)}
        except Exception:
            logger.warning("live account snapshot unavailable — using latest telemetry", exc_info=True)
            import psycopg

            with psycopg.connect(store.database_url, autocommit=True) as conn:
                row = conn.execute(
                    """SELECT equity, day_start_equity FROM portfolio_telemetry
                       ORDER BY ts DESC, id DESC LIMIT 1"""
                ).fetchone()
            if row is None:
                raise RuntimeError("no live account and no telemetry — cannot build snapshot")
            equity, day_start = float(row[0]), float(row[1])
            return {"equity": equity, "peak_equity": equity,
                    "day_start_equity": day_start, "open_positions_count": 0}
    return snapshot


def main() -> None:
    from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler

    from db.store import TelemetryStore
    from execution.propr_client import ProprExecutionService
    from telegram_control import handlers
    from telegram_control.auth import allowed_user_ids
    from telegram_control.handlers import ControlServices

    token = os.environ["BTC_SIGNAL_BOT_TELEGRAM_TOKEN"]
    if not allowed_user_ids():
        logger.error("No admin IDs configured — the control plane will reject every command.")

    store = TelemetryStore()
    store.apply_schema()
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    execution = ProprExecutionService(
        execution_enabled=bool(cfg.get("feature_flags", {}).get("execution_enabled", False)),
    )
    try:
        execution.setup()
    except Exception:
        logger.warning("Propr account setup failed (no active challenge yet?) — "
                       "live account features degrade to telemetry fallback", exc_info=True)

    services = ControlServices(
        store=store, execution=execution,
        account_snapshot=build_account_snapshot(store, execution),
    )

    def wire(fn):
        @functools.wraps(fn)
        async def wrapped(update, context):
            await fn(update, context, services)
        return wrapped

    async def on_error(update, context):
        logger.error("handler exception (update=%s)", getattr(update, "update_id", "?"),
                     exc_info=context.error)

    app = ApplicationBuilder().token(token).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("kill", wire(handlers.cmd_kill), block=False))  # un-blockable
    app.add_handler(CommandHandler("run", wire(handlers.cmd_run)))
    app.add_handler(CommandHandler("pause", wire(handlers.cmd_pause)))
    app.add_handler(CommandHandler("dashboard", wire(handlers.cmd_dashboard)))
    app.add_handler(CommandHandler("risk", wire(handlers.cmd_risk)))
    app.add_handler(CommandHandler("settings", wire(handlers.cmd_settings)))
    app.add_handler(CallbackQueryHandler(wire(handlers.cb_settings), pattern=r"^stg_"))
    app.add_handler(CallbackQueryHandler(wire(handlers.cb_take_signal), pattern=r"^take_"))
    app.add_handler(CallbackQueryHandler(wire(handlers.cb_skip_signal), pattern=r"^skip_"))
    app.add_handler(CallbackQueryHandler(wire(handlers.cb_close_fraction), pattern=r"^close_"))
    app.add_handler(CallbackQueryHandler(wire(handlers.cb_sl_breakeven), pattern=r"^slbe_"))

    logger.info("telegram control plane starting (long polling)")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
