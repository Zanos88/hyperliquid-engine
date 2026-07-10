"""Regression: forward-test report determinism + post-flip position display.

Targets the STAGING Supabase project only, exactly like tests/test_db_trigger.py
— reads TEST_DATABASE_URL exclusively, skips cleanly when unset, and uses an
isolated symbol so it never touches the real BTC forward-test marks.
"""
from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")

_LIVE_PROJECT_REF = "lnycymeylmhjqpwtdint"
if TEST_DB_URL and _LIVE_PROJECT_REF in TEST_DB_URL:
    raise RuntimeError("TEST_DATABASE_URL points at the LIVE Supabase project — refusing to run.")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="no TEST_DATABASE_URL — forward-report tests need the staging Postgres"
)

SYMBOL = "TESTBUG1"  # isolated from the real forward test's BTC rows


@pytest.fixture()
def conn():
    from db.store import TelemetryStore
    store = TelemetryStore(database_url=TEST_DB_URL)
    store.apply_schema()
    c = store._connect()
    c.execute("DELETE FROM trend_forward_marks WHERE symbol = %s", (SYMBOL,))
    yield c
    c.execute("DELETE FROM trend_forward_marks WHERE symbol = %s", (SYMBOL,))


def _insert(conn, strategy, open_ms, position, flipped, equity):
    conn.execute(
        "INSERT INTO trend_forward_marks (bar_open_time_ms, bar_close_utc, strategy, "
        "symbol, close, position, bar_log_return, equity, flipped) "
        "VALUES (%s, to_timestamp(%s/1000.0), %s, %s, 100, %s, 0, %s, %s)",
        (open_ms, open_ms + 86_399_999, strategy, SYMBOL, position, equity, flipped),
    )


def test_report_is_deterministic_and_shows_post_flip_position(conn):
    from forward_test import report_text

    day = 86_400_000
    # Inception FLAT, then a mark whose close flipped 0 -> 1: the report's
    # pos column must show the CURRENT stance (LONG), not the stale
    # position-into-bar (FLAT) — the 2026-07-10 display fix.
    _insert(conn, "t_flip", 0, 0, False, 100_000)
    _insert(conn, "t_flip", day, 0, True, 99_925)
    # A no-flip strategy stays FLAT.
    _insert(conn, "t_flat", 0, 0, False, 100_000)
    _insert(conn, "t_flat", day, 0, False, 100_000)

    first = report_text(conn, symbol=SYMBOL)
    second = report_text(conn, symbol=SYMBOL)
    assert first is not None
    assert first == second  # identical DB state -> identical output, always

    flip_row = next(l for l in first.splitlines() if l.startswith("t_flip"))
    flat_row = next(l for l in first.splitlines() if l.startswith("t_flat"))
    assert "LONG" in flip_row
    assert "FLAT" in flat_row
