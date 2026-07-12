"""Step-3 stress tests for the challenge-tier parameterization (STAGING ONLY).

Drives synthetic equity paths through the REAL persistence + enforcement
stack on the staging Supabase project: challenge_config / equity_hwm tables,
store.update_hwm ratchet, Guardian soft/hard buffers, and the rewritten
floor-guard trigger. Scenarios per the reparameterization spec:

  1 rising            — floor ratchets up continuously with the HWM
  2 rise-then-fall    — floor HOLDS at the peak-derived level; guardian
                        soft-halts then hard-flattens at the correct levels
  3 choppy            — no spurious floor movement, no false halts
  4 restart           — a fresh process reads the HWM from the DB and
                        resumes with the identical floor
  5 static regression — re-configured as the 1-Step-style static tier, the
                        floors reproduce the historical formula exactly

Refuses to run against anything but the staging project (TEST_DATABASE_URL,
live-ref guard — same discipline as tests/test_db_trigger.py).

    $env:TEST_DATABASE_URL="<staging session-pooler URI>"
    python scripts/stress_trailing_floor.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402

from db.store import TelemetryStore  # noqa: E402
from guardian import HARD_BUFFER_USD, SOFT_BUFFER_USD, Guardian  # noqa: E402
from risk.challenge import ChallengeConfig, binding_floor  # noqa: E402
from strategy.signals import SignalDirection  # noqa: E402  (import sanity)

_LIVE_REF = "lnycymeylmhjqpwtdint"
URL = os.environ.get("TEST_DATABASE_URL")
if not URL:
    sys.exit("TEST_DATABASE_URL not set — stress tests run against staging ONLY")
if _LIVE_REF in URL:
    sys.exit("TEST_DATABASE_URL points at the LIVE project — refusing")

PASS = "PASS"


class FakeExecution:
    def __init__(self):
        self.kills = 0

    def kill_sequence(self):
        self.kills += 1
        return {"dry_run": True, "cancelled_order_ids": [], "closed": []}


def set_config(conn, drawdown_type, dd_pct, daily_pct, initial=100_000):
    conn.execute(
        """UPDATE challenge_config SET drawdown_type=%s, max_drawdown_pct=%s,
           daily_loss_pct=%s, initial_balance=%s, updated_at=now(),
           updated_by='stress_test' WHERE id=1""",
        (drawdown_type, dd_pct, daily_pct, initial))


def reset_hwm(conn, value=100_000):
    conn.execute("UPDATE equity_hwm SET hwm=%s, updated_at=now() WHERE id=1", (value,))


def check(label, cond, detail=""):
    status = PASS if cond else "FAIL"
    print(f"  [{status}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        raise SystemExit(f"STRESS FAILURE: {label}")


def main() -> None:
    store = TelemetryStore(database_url=URL)
    store.apply_schema()
    conn = store._connect()
    conn.execute("TRUNCATE portfolio_telemetry, trade_execution_ledger, risk_events")
    gold = ChallengeConfig("trailing", 8.0, 5.0, 100_000.0)

    print("=== scenario 1: steadily rising equity (trailing 8%/5%) ===")
    set_config(conn, "trailing", 8, 5)
    reset_hwm(conn)
    prev_floor = 0.0
    for eq in (100_000, 102_000, 104_500, 107_000, 110_000, 112_000):
        hwm = store.update_hwm(eq)
        # fixed day_start: one rising trading day, so the dd-vs-daily
        # handover is visible (daily 95,000 binds until hwm > 103,261)
        floor = binding_floor(gold, day_start_equity=100_000, hwm=hwm)
        check(f"eq {eq:,}: hwm {hwm:,.0f} floor {floor:,.2f} >= prev {prev_floor:,.2f}",
              hwm == eq and floor >= prev_floor)
        prev_floor = floor
    check("final floor = max(95,000 daily, 112,000×0.92 dd) = 103,040",
          abs(prev_floor - 103_040) < 1e-6)

    print("=== scenario 2: rise then fall — floor holds; guardian halts correctly ===")
    reset_hwm(conn)
    store.update_hwm(110_000)  # peak
    execution = FakeExecution()
    g = Guardian(store=store, execution=execution, day_start_equity=104_000,
                 telegram=None, challenge_cfg=gold, hwm=store.get_hwm())
    floor = g.binding_floor()
    check("peak 110,000 -> binding floor 101,200 (dd dominates daily 99,000)",
          abs(floor - 101_200) < 1e-6)
    for eq in (108_000, 105_000, 103_000):
        g.observe_hwm(eq)
        actions = g.on_equity(eq)
        check(f"eq {eq:,}: no halt (floor {g.binding_floor():,.0f} held)",
              actions == [] and abs(g.binding_floor() - 101_200) < 1e-6)
    actions = g.on_equity(101_650)   # inside floor + 500 soft buffer
    check("eq 101,650 -> SOFT-HALT (<= 101,200 + 500)", actions == ["soft_halt"],
          f"engine_state={store.get_engine_state()}")
    actions = g.on_equity(101_350)   # inside floor + 200 hard buffer
    check("eq 101,350 -> HARD-FLATTEN (<= 101,200 + 200)",
          actions == ["hard_flatten"] and execution.kills == 1,
          f"engine_state={store.get_engine_state()}")
    check("HWM never moved down during the fall", store.get_hwm() == 110_000)

    print("=== scenario 2b: floor-guard trigger blocks at the trailing floor ===")
    store.record_telemetry(equity=101_600, day_start_equity=104_000, engine_state="ACTIVE")
    from execution.propr_client import OrderIntent
    from ulid import ULID
    # worst case 101,600 - 0.5*1,000 = 101,100 <= 101,200+200 -> BLOCK
    blocked = store.record_intent(OrderIntent(
        intent_id=str(ULID()), asset="BTC", side="buy", position_side="long",
        order_type="market", quantity="0.500", time_in_force="IOC",
        purpose="entry", risk_entry_price="60000", risk_stop_price="58000",
    ), dry_run=True)
    check("crossing intent blocked by rewritten trigger", blocked is False)
    safe = store.record_intent(OrderIntent(
        intent_id=str(ULID()), asset="BTC", side="buy", position_side="long",
        order_type="market", quantity="0.010", time_in_force="IOC",
        purpose="entry", risk_entry_price="60000", risk_stop_price="59900",
    ), dry_run=True)
    check("safe intent admitted (worst case clears trailing floor + 200)", safe is True)

    print("=== scenario 3: choppy/sideways — no spurious movement ===")
    reset_hwm(conn)
    store.update_hwm(100_000)
    g3 = Guardian(store=store, execution=FakeExecution(), day_start_equity=100_000,
                  telegram=None, challenge_cfg=gold, hwm=store.get_hwm())
    store.set_engine_state("ACTIVE", "stress_test")
    floors = set()
    for eq in (100_000, 99_400, 100_600, 99_800, 100_900, 100_200):
        g3.observe_hwm(eq)
        actions = g3.on_equity(eq)
        check(f"eq {eq:,}: no halt", actions == [])
        floors.add(round(g3.binding_floor(), 2))
    check("floor moved only on new highs",
          floors == {95_000.0, round(100_900 * 0.92, 2)} or floors == {95_000.0},
          f"observed floors {sorted(floors)}")
    check("local ratchet holds the max seen (100,900)", g3.hwm == 100_900)
    # persistence happens on the telemetry throttle in the real loop —
    # mirror it once and confirm the DB ratchet agrees
    check("persisted hwm = 100,900 after throttle write",
          store.update_hwm(g3.hwm) == 100_900)

    print("=== scenario 4: restart mid-sequence — HWM survives via DB ===")
    store2 = TelemetryStore(database_url=URL)  # fresh 'process'
    resumed_hwm = store2.update_hwm(100_500)   # current equity below old peak
    check("fresh store resumes HWM 100,900 (GREATEST beats lower current equity)",
          resumed_hwm == 100_900)
    g4 = Guardian(store=store2, execution=FakeExecution(), day_start_equity=100_500,
                  telegram=None, challenge_cfg=store2.get_challenge_config(),
                  hwm=resumed_hwm)
    check("restarted guardian floor identical (95,500 daily vs 92,828 dd -> 95,500)",
          abs(g4.binding_floor() - binding_floor(gold, 100_500, 100_900)) < 1e-6,
          f"floor {g4.binding_floor():,.2f}")

    print("=== scenario 5: static-tier regression (1-Step shape) ===")
    set_config(conn, "static", 6, 3)
    cfg_static = store.get_challenge_config()
    for day_start, expected in ((100_000, 97_000), (96_000, 94_000), (98_500, 95_500)):
        got = binding_floor(cfg_static, day_start, hwm=store.get_hwm())
        check(f"day_start {day_start:,} -> floor {expected:,} (old formula)",
              abs(got - expected) < 1e-6, f"got {got:,.2f}")
    conn.execute("TRUNCATE portfolio_telemetry, trade_execution_ledger, risk_events")
    store.record_telemetry(equity=97_600, day_start_equity=100_000, engine_state="ACTIVE")
    blocked = store.record_intent(OrderIntent(
        intent_id=str(ULID()), asset="BTC", side="buy", position_side="long",
        order_type="market", quantity="0.500", time_in_force="IOC",
        purpose="entry", risk_entry_price="60000", risk_stop_price="59000",
    ), dry_run=True)
    check("historical trigger case reproduces under static config (blocked)",
          blocked is False)

    print("=== scenario 6: activation-flip rehearsal (Zane's Step-4 precondition) ===")
    # Pre-flip reality: static config while PAPER trading ratchets the HWM.
    set_config(conn, "static", 6, 3)
    reset_hwm(conn)
    store.update_hwm(105_000)  # paper inflation before activation
    check("pre-flip: paper-inflated HWM 105,000 (harmless under static config)",
          store.get_hwm() == 105_000)
    # The EXACT Step-4 flip transaction from the doc: config -> Gold 2-Step
    # + DIRECT reset of the HWM to the real account equity (100,000).
    conn.execute("BEGIN")
    set_config(conn, "trailing", 8, 5)
    conn.execute("UPDATE equity_hwm SET hwm=%s, updated_at=now() WHERE id=1", (100_000,))
    conn.execute("COMMIT")
    check("flip: direct reset DID lower the HWM to 100,000", store.get_hwm() == 100_000)
    cfg_flipped = store.get_challenge_config()
    floor_after = binding_floor(cfg_flipped, day_start_equity=100_000, hwm=store.get_hwm())
    check("post-flip floors recompute from the RESET base "
          "(daily 95,000 binds over dd 92,000 — not 96,600 from the paper peak)",
          abs(floor_after - 95_000) < 1e-6, f"floor {floor_after:,.2f}")
    check("ratchet integrity survives the reset: update_hwm(99,000) cannot lower",
          store.update_hwm(99_000) == 100_000)
    check("normal ratcheting resumes: update_hwm(101,000) -> 101,000",
          store.update_hwm(101_000) == 101_000)
    g6 = Guardian(store=store, execution=FakeExecution(), day_start_equity=100_000,
                  telegram=None, challenge_cfg=cfg_flipped, hwm=store.get_hwm())
    check("guardian built post-flip reads the correct trailing floor",
          abs(g6.binding_floor() - binding_floor(cfg_flipped, 100_000, 101_000)) < 1e-6,
          f"floor {g6.binding_floor():,.2f}")

    # leave staging in the seed state
    set_config(conn, "static", 6, 3)
    reset_hwm(conn)
    print("\nALL SCENARIOS PASSED — staging left at the static seed posture.")


if __name__ == "__main__":
    main()
