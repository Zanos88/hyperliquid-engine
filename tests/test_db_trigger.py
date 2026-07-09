"""Phase 3 acceptance tests: the Postgres floor-guard trigger.

Runs ONLY against the dedicated staging Supabase project — never the live
one. The suite reads TEST_DATABASE_URL exclusively (the staging session-
pooler URI) and is skipped cleanly when it is unset, so the rest of the
suite stays network-free. It deliberately does NOT read DATABASE_URL /
DATABASE_PUBLIC_URL: those point at the live engine's DB, and a stray write
here left the live engine PAUSED ~5.4h on 2026-07-08. Run with (PowerShell):

    $env:TEST_DATABASE_URL="postgresql://postgres.<ref>:<pw>@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    python -m pytest tests/test_db_trigger.py -v
"""
from __future__ import annotations

import os

import pytest
from ulid import ULID

psycopg = pytest.importorskip("psycopg")

# DB tests target ONLY the staging Supabase project, via TEST_DATABASE_URL.
# We never fall back to DATABASE_URL/DATABASE_PUBLIC_URL — those are the live
# engine's DB, and a stray write here paused the live engine ~5.4h on
# 2026-07-08. The guard below makes pointing at live impossible by accident.
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")

_LIVE_PROJECT_REF = "lnycymeylmhjqpwtdint"
if TEST_DB_URL and _LIVE_PROJECT_REF in TEST_DB_URL:
    raise RuntimeError(
        f"TEST_DATABASE_URL points at the LIVE Supabase project ({_LIVE_PROJECT_REF}). "
        "DB tests must target the staging project only — refusing to run."
    )

HAS_DB = bool(TEST_DB_URL)
pytestmark = pytest.mark.skipif(
    not HAS_DB, reason="no TEST_DATABASE_URL — DB trigger tests need the staging Postgres"
)

if HAS_DB:
    from db.store import TelemetryStore
    from execution.propr_client import OrderIntent


@pytest.fixture(scope="module")
def store():
    s = TelemetryStore(database_url=TEST_DB_URL)
    s.apply_schema()
    return s


@pytest.fixture(autouse=True)
def clean_tables(store):
    with psycopg.connect(store.database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE portfolio_telemetry, trade_execution_ledger, risk_events")
    yield


def entry_intent(quantity="0.500", entry="60000", stop="59000") -> "OrderIntent":
    return OrderIntent(
        intent_id=str(ULID()), asset="BTC", side="buy", position_side="long",
        order_type="market", quantity=quantity, time_in_force="IOC",
        purpose="entry", risk_entry_price=entry, risk_stop_price=stop,
    )


def kill_close_intent() -> "OrderIntent":
    return OrderIntent(
        intent_id=str(ULID()), asset="BTC", side="sell", position_side="long",
        order_type="market", quantity="0.500", time_in_force="IOC",
        reduce_only=True, close_position=True, purpose="kill_close",
    )


def count(store, table) -> int:
    with psycopg.connect(store.database_url, autocommit=True) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_trigger_blocks_boundary_crossing_intent(store):
    # equity 97,600, day-start 100k -> binding floor 97,000 (+200 = 97,200).
    # 0.5 BTC with $1,000 stop distance risks $500 -> worst case 97,100 -> BLOCK.
    store.record_telemetry(equity=97_600, day_start_equity=100_000, engine_state="ACTIVE")
    ok = store.record_intent(entry_intent(quantity="0.500"), dry_run=True)

    assert ok is False
    assert count(store, "trade_execution_ledger") == 0        # row rejected
    with psycopg.connect(store.database_url, autocommit=True) as conn:
        events = conn.execute("SELECT event_type FROM risk_events").fetchall()
    assert ("db_trigger_block",) in events                     # block recorded


def test_trigger_admits_safe_intent(store):
    store.record_telemetry(equity=100_000, day_start_equity=100_000, engine_state="ACTIVE")
    ok = store.record_intent(entry_intent(quantity="0.500"), dry_run=True,
                             risk_usd=500.0, attenuation_applied=1.0,
                             indicators_snapshot={"fisher": 1.2, "bias": "BULLISH"})
    assert ok is True
    assert count(store, "trade_execution_ledger") == 1


def test_trigger_never_blocks_reducing_intents(store):
    # Same dangerous telemetry as the blocking test — but a kill close must
    # ALWAYS be admitted (blocking risk-reduction would be catastrophic).
    store.record_telemetry(equity=94_050, day_start_equity=100_000, engine_state="KILLED")
    ok = store.record_intent(kill_close_intent(), dry_run=False)
    assert ok is True
    assert count(store, "trade_execution_ledger") == 1


def test_trigger_fails_closed_without_telemetry(store):
    ok = store.record_intent(entry_intent(), dry_run=True)     # no telemetry rows
    assert ok is False
    assert count(store, "trade_execution_ledger") == 0


def test_trigger_fails_closed_without_risk_prices(store):
    store.record_telemetry(equity=100_000, day_start_equity=100_000, engine_state="ACTIVE")
    bare = OrderIntent(
        intent_id=str(ULID()), asset="BTC", side="buy", position_side="long",
        order_type="market", quantity="0.5", time_in_force="IOC", purpose="entry",
    )
    ok = store.record_intent(bare, dry_run=True)
    assert ok is False


def test_strategy_settings_roundtrip(store):
    s = store.get_strategy_settings()
    assert s["mode"] in ("production", "test")
    store.set_strategy_setting("mode", "test", updated_by="test")
    assert store.get_strategy_settings()["active_bias_tf"] == store.get_strategy_settings()["test_bias_tf"]
    store.set_strategy_setting("prod_bias_tf", "8h", updated_by="test")
    assert store.get_strategy_settings()["prod_bias_tf"] == "8h"
    with pytest.raises(Exception):
        store.set_strategy_setting("prod_trigger_tf", "1w", updated_by="test")  # trigger >= bias
    # restore seeds
    store.set_strategy_setting("prod_bias_tf", "4h", updated_by="test")
    store.set_strategy_setting("mode", "production", updated_by="test")


def test_engine_state_roundtrip(store):
    # Runs against the STAGING project (TEST_DATABASE_URL), so this no longer
    # touches the live engine. The restore-in-finally is kept as defense in
    # depth — an earlier version ran against live and a leftover PAUSED write
    # from this test paused the live engine ~5.4h on 2026-07-08.
    initial = store.get_engine_state()
    assert initial in ("ACTIVE", "PAUSED", "KILLED")
    try:
        store.set_engine_state("ACTIVE", updated_by="test")
        assert store.get_engine_state() == "ACTIVE"
        store.set_engine_state("KILLED", updated_by="test")
        assert store.get_engine_state() == "KILLED"
        with pytest.raises(ValueError):
            store.set_engine_state("BANANAS", updated_by="test")
        store.set_engine_state("PAUSED", updated_by="test")
    finally:
        store.set_engine_state(initial, updated_by="test_restore")
    assert store.get_engine_state() == initial
