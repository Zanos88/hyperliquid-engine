"""Postgres telemetry store (V2 build report section 7).

Deployment-agnostic: connects via DATABASE_URL (Railway internal) or
DATABASE_PUBLIC_URL (external/local runs). Low-cadence system — a fresh
autocommit connection per operation keeps the failure surface small; no
pooling needed at 1H-signal cadence with 5s-throttled telemetry.

A blocked intent (floor-guard trigger) is NOT an error path to swallow:
`record_intent` returns False and writes a `db_trigger_block` risk event
in a new transaction, and the caller must refuse to dispatch.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path

import psycopg

from execution.propr_client import OrderIntent

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    if not url:
        raise RuntimeError("DATABASE_URL (or DATABASE_PUBLIC_URL) not set")
    # Local/test runs can't reach Railway's internal hostname — fall back
    # to the public proxy when both are present and internal is private.
    if ".railway.internal" in url and os.environ.get("DATABASE_PUBLIC_URL"):
        return os.environ["DATABASE_PUBLIC_URL"]
    return url


class TelemetryStore:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or resolve_database_url()
        self._conn: psycopg.Connection | None = None

    def _connect(self) -> psycopg.Connection:
        """Reuse one autocommit connection per store (per process).

        A fresh TLS connection through the public proxy costs seconds;
        multi-call handler paths were stacking those and blowing
        Telegram's callback-answer window. Reconnects transparently if
        the cached connection has died.
        """
        if self._conn is None or self._conn.closed or self._conn.broken:
            self._conn = psycopg.connect(self.database_url, autocommit=True)
        return self._conn

    def apply_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(sql)
        logger.info("telemetry schema applied")

    # ── telemetry ──

    def record_telemetry(
        self,
        equity: float,
        day_start_equity: float,
        engine_state: str,
        balance: float | None = None,
        unrealized_pnl: float | None = None,
        symbol: str = "BTC",
    ) -> None:
        daily_floor = day_start_equity - 3000
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                """INSERT INTO portfolio_telemetry
                   (symbol, equity, balance, unrealized_pnl, day_start_equity,
                    distance_to_daily_floor, distance_to_static_floor, engine_state)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (symbol, equity, balance, unrealized_pnl, day_start_equity,
                 equity - daily_floor, equity - 94_000, engine_state),
            )

    # ── order intents (floor-guard trigger fires here) ──

    def record_intent(
        self,
        intent: OrderIntent,
        dry_run: bool,
        risk_usd: float | None = None,
        attenuation_applied: float | None = None,
        indicators_snapshot: dict | None = None,
        symbol: str = "BTC",
    ) -> bool:
        """Insert the intent row BEFORE dispatch. Returns False (and logs a
        risk event) if the floor-guard trigger blocks it — caller must not
        dispatch in that case."""
        try:
            with contextlib.nullcontext(self._connect()) as conn:
                conn.execute(
                    """INSERT INTO trade_execution_ledger
                       (symbol, intent_id, order_group_id, purpose, side, position_side,
                        order_type, quantity, price, trigger_price, reduce_only,
                        close_position, risk_entry_price, risk_stop_price, risk_usd,
                        attenuation_applied, dry_run, indicators_snapshot)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (symbol, intent.intent_id, intent.order_group_id, intent.purpose,
                     intent.side, intent.position_side, intent.order_type,
                     intent.quantity, intent.price, intent.trigger_price,
                     intent.reduce_only, intent.close_position,
                     intent.risk_entry_price, intent.risk_stop_price,
                     risk_usd, attenuation_applied, dry_run,
                     json.dumps(indicators_snapshot) if indicators_snapshot else None),
                )
            return True
        except psycopg.errors.RaiseException as exc:
            logger.warning("floor-guard trigger BLOCKED intent %s: %s", intent.intent_id, exc)
            self.record_risk_event(
                "db_trigger_block",
                {"intent_id": intent.intent_id, "purpose": intent.purpose, "error": str(exc)},
            )
            return False

    def mark_dispatched(self, intent_id: str) -> None:
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                "UPDATE trade_execution_ledger SET dispatched = true WHERE intent_id = %s",
                (intent_id,),
            )

    # ── risk events ──

    def record_risk_event(self, event_type: str, detail: dict | None = None) -> None:
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                "INSERT INTO risk_events (event_type, detail) VALUES (%s, %s)",
                (event_type, json.dumps(detail) if detail else None),
            )

    # ── runtime risk params (set via /risk, read by the engine) ──

    def get_risk_params(self) -> dict:
        with contextlib.nullcontext(self._connect()) as conn:
            row = conn.execute(
                "SELECT risk_pct, alpha, max_concurrent FROM risk_params WHERE id = 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("risk_params row missing — run apply_schema()")
        return {"risk_pct": float(row[0]), "alpha": float(row[1]), "max_concurrent": int(row[2])}

    def set_risk_param(self, name: str, value: float, updated_by: str) -> dict:
        """Update one param (DB CHECK constraints enforce bounds). Logs
        old->new to risk_events. Returns the new params dict."""
        if name not in ("risk_pct", "alpha", "max_concurrent"):
            raise ValueError(f"unknown risk param {name}")
        old = self.get_risk_params()
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                f"UPDATE risk_params SET {name} = %s, updated_at = now(), updated_by = %s WHERE id = 1",
                (value, updated_by),
            )
        new = self.get_risk_params()
        self.record_risk_event("risk_param_change", {
            "param": name, "old": old[name], "new": new[name], "by": updated_by,
        })
        return new

    # ── indicator toggles (set via /settings -> Indicators) ──

    def get_indicator_config(self) -> dict:
        with contextlib.nullcontext(self._connect()) as conn:
            row = conn.execute(
                """SELECT bias_sr, fisher, obv, rsi, ichimoku, ichimoku_variant
                   FROM indicator_config WHERE id = 1"""
            ).fetchone()
        if row is None:
            raise RuntimeError("indicator_config row missing — run apply_schema()")
        return {"bias_sr": row[0], "fisher": row[1], "obv": row[2],
                "rsi": row[3], "ichimoku": row[4], "ichimoku_variant": row[5]}

    def set_indicator_toggle(self, name: str, enabled: bool, updated_by: str) -> dict:
        from strategy.signals import INDICATOR_NAMES

        if name not in INDICATOR_NAMES:
            raise ValueError(f"unknown indicator {name} — allowed: {INDICATOR_NAMES}")
        old = self.get_indicator_config()
        candidate = {**old, name: enabled}
        if not any(candidate[n] for n in INDICATOR_NAMES):
            raise ValueError("at least one indicator must remain enabled")
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                f"UPDATE indicator_config SET {name} = %s, updated_at = now(), updated_by = %s WHERE id = 1",
                (enabled, updated_by),
            )
        new = self.get_indicator_config()
        self.record_risk_event("settings_change", {
            "setting": f"indicator:{name}", "old": old[name], "new": new[name], "by": updated_by,
        })
        return new

    def set_ichimoku_variant(self, variant: str, updated_by: str) -> dict:
        if variant not in ("standard", "crypto"):
            raise ValueError(f"ichimoku variant must be standard or crypto, got {variant!r}")
        old = self.get_indicator_config()
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                "UPDATE indicator_config SET ichimoku_variant = %s, updated_at = now(), updated_by = %s WHERE id = 1",
                (variant, updated_by),
            )
        new = self.get_indicator_config()
        self.record_risk_event("settings_change", {
            "setting": "indicator:ichimoku_variant", "old": old["ichimoku_variant"],
            "new": new["ichimoku_variant"], "by": updated_by,
        })
        return new

    # ── market state (engine-written levels for the manual trade panel) ──

    def record_market_state(self, last_price: float, bias: str,
                            long_stop: float | None, long_target: float | None,
                            short_stop: float | None, short_target: float | None,
                            symbol: str = "BTC") -> None:
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                """INSERT INTO market_state (id, ts, symbol, last_price, bias,
                                             long_stop, long_target, short_stop, short_target)
                   VALUES (1, now(), %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET
                       ts = now(), symbol = EXCLUDED.symbol,
                       last_price = EXCLUDED.last_price, bias = EXCLUDED.bias,
                       long_stop = EXCLUDED.long_stop, long_target = EXCLUDED.long_target,
                       short_stop = EXCLUDED.short_stop, short_target = EXCLUDED.short_target""",
                (symbol, last_price, bias, long_stop, long_target, short_stop, short_target),
            )

    def get_market_state(self) -> dict | None:
        with contextlib.nullcontext(self._connect()) as conn:
            row = conn.execute(
                """SELECT ts, symbol, last_price, bias, long_stop, long_target,
                          short_stop, short_target FROM market_state WHERE id = 1"""
            ).fetchone()
        if row is None:
            return None
        keys = ("ts", "symbol", "last_price", "bias", "long_stop", "long_target",
                "short_stop", "short_target")
        out = dict(zip(keys, row))
        for k in ("last_price", "long_stop", "long_target", "short_stop", "short_target"):
            out[k] = float(out[k]) if out[k] is not None else None
        return out

    # ── strategy settings (set via /settings, read by the engine) ──

    def get_strategy_settings(self) -> dict:
        with contextlib.nullcontext(self._connect()) as conn:
            row = conn.execute(
                """SELECT mode, prod_bias_tf, prod_trigger_tf, test_bias_tf, test_trigger_tf
                   FROM strategy_settings WHERE id = 1"""
            ).fetchone()
        if row is None:
            raise RuntimeError("strategy_settings row missing — run apply_schema()")
        mode, pb, pt, tb, tt = row
        active_bias, active_trigger = (pb, pt) if mode == "production" else (tb, tt)
        return {
            "mode": mode,
            "prod_bias_tf": pb, "prod_trigger_tf": pt,
            "test_bias_tf": tb, "test_trigger_tf": tt,
            "active_bias_tf": active_bias, "active_trigger_tf": active_trigger,
        }

    def set_strategy_setting(self, name: str, value: str, updated_by: str) -> dict:
        """Update mode or one timeframe. Validates bias > trigger for the
        affected pair BEFORE writing (plus DB CHECKs on allowed values).
        Logs old->new to risk_events. Returns the new settings dict."""
        from strategy.timeframes import validate_combo

        allowed = ("mode", "prod_bias_tf", "prod_trigger_tf", "test_bias_tf", "test_trigger_tf")
        if name not in allowed:
            raise ValueError(f"unknown strategy setting {name}")

        old = self.get_strategy_settings()
        candidate = {**old, name: value}
        if name != "mode":
            validate_combo(candidate["prod_bias_tf"], candidate["prod_trigger_tf"])
            validate_combo(candidate["test_bias_tf"], candidate["test_trigger_tf"])
        elif value not in ("production", "test"):
            raise ValueError(f"mode must be production or test, got {value!r}")

        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                f"UPDATE strategy_settings SET {name} = %s, updated_at = now(), updated_by = %s WHERE id = 1",
                (value, updated_by),
            )
        new = self.get_strategy_settings()
        self.record_risk_event("settings_change", {
            "setting": name, "old": old[name], "new": new[name], "by": updated_by,
        })
        return new

    # ── pending signal frames (Frame A, cross-process) ──

    def create_pending_signal(self, signal_id: str, direction: str, entry: float,
                              stop: float, target: float, reward_risk: float,
                              indicators_snapshot: dict | None = None) -> None:
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                """INSERT INTO pending_signals (signal_id, direction, entry, stop, target,
                                                reward_risk, indicators_snapshot)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (signal_id, direction, entry, stop, target, reward_risk,
                 json.dumps(indicators_snapshot) if indicators_snapshot else None),
            )

    def get_pending_signal(self, signal_id: str) -> dict | None:
        with contextlib.nullcontext(self._connect()) as conn:
            row = conn.execute(
                """SELECT signal_id, direction, entry, stop, target, reward_risk, status
                   FROM pending_signals WHERE signal_id = %s""",
                (signal_id,),
            ).fetchone()
        if row is None:
            return None
        return {"signal_id": row[0], "direction": row[1], "entry": float(row[2]),
                "stop": float(row[3]), "target": float(row[4]),
                "reward_risk": float(row[5]), "status": row[6]}

    def resolve_pending_signal(self, signal_id: str, status: str, resolved_by: str) -> None:
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                """UPDATE pending_signals SET status = %s, resolved_at = now(), resolved_by = %s
                   WHERE signal_id = %s AND status = 'pending'""",
                (status, resolved_by, signal_id),
            )

    # ── engine state (cross-process) ──

    def get_engine_state(self) -> str:
        with contextlib.nullcontext(self._connect()) as conn:
            row = conn.execute("SELECT state FROM engine_state WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("engine_state row missing — run apply_schema()")
        return row[0]

    def set_engine_state(self, state: str, updated_by: str) -> None:
        if state not in ("ACTIVE", "PAUSED", "KILLED"):
            raise ValueError(f"invalid engine state {state}")
        with contextlib.nullcontext(self._connect()) as conn:
            conn.execute(
                "UPDATE engine_state SET state = %s, updated_at = now(), updated_by = %s WHERE id = 1",
                (state, updated_by),
            )
        logger.info("engine_state -> %s (by %s)", state, updated_by)
