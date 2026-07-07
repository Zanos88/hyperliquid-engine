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

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, autocommit=True)

    def apply_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
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
        with self._connect() as conn:
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
            with self._connect() as conn:
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
        with self._connect() as conn:
            conn.execute(
                "UPDATE trade_execution_ledger SET dispatched = true WHERE intent_id = %s",
                (intent_id,),
            )

    # ── risk events ──

    def record_risk_event(self, event_type: str, detail: dict | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO risk_events (event_type, detail) VALUES (%s, %s)",
                (event_type, json.dumps(detail) if detail else None),
            )

    # ── engine state (cross-process) ──

    def get_engine_state(self) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT state FROM engine_state WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("engine_state row missing — run apply_schema()")
        return row[0]

    def set_engine_state(self, state: str, updated_by: str) -> None:
        if state not in ("ACTIVE", "PAUSED", "KILLED"):
            raise ValueError(f"invalid engine state {state}")
        with self._connect() as conn:
            conn.execute(
                "UPDATE engine_state SET state = %s, updated_at = now(), updated_by = %s WHERE id = 1",
                (state, updated_by),
            )
        logger.info("engine_state -> %s (by %s)", state, updated_by)
