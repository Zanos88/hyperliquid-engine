"""Phase 4 acceptance tests: guardian soft-halt / hard-flatten on a
simulated equity slide (mocked feed — no network, no real kill)."""
from __future__ import annotations

from datetime import datetime, timezone

from guardian import Guardian, equity_from_account_event


class FakeStore:
    def __init__(self, state="ACTIVE"):
        self.state = state
        self.events: list[tuple[str, dict]] = []
        self.telemetry: list[dict] = []

    def get_engine_state(self):
        return self.state

    def set_engine_state(self, state, updated_by):
        self.state = state

    def record_risk_event(self, event_type, detail=None):
        self.events.append((event_type, detail or {}))

    def record_telemetry(self, **kwargs):
        self.telemetry.append(kwargs)


class FakeExecution:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.kill_calls = 0

    def kill_sequence(self):
        self.kill_calls += 1
        return {"dry_run": self.dry_run, "cancelled_order_ids": ["o1"], "closed": ["p1"]}


class FakeTelegram:
    def __init__(self):
        self.sent: list[str] = []

    def send(self, text):
        self.sent.append(text)
        return True


def make_guardian(day_start=100_000.0, state="ACTIVE"):
    store, execution, tg = FakeStore(state), FakeExecution(), FakeTelegram()
    return Guardian(store=store, execution=execution, day_start_equity=day_start, telegram=tg), store, execution, tg


def test_equity_slide_soft_then_hard():
    g, store, execution, tg = make_guardian(day_start=100_000)   # floor 97,000
    assert g.on_equity(99_000) == []                             # healthy
    assert g.on_equity(97_450) == ["soft_halt"]                  # <= 97,500
    assert store.state == "PAUSED"
    assert ("guardian_soft_halt" in [e for e, _ in store.events])
    assert execution.kill_calls == 0

    assert g.on_equity(97_150) == ["hard_flatten"]               # <= 97,200
    assert store.state == "KILLED"
    assert execution.kill_calls == 1
    assert ("guardian_hard_flatten" in [e for e, _ in store.events])
    assert len(tg.sent) == 2                                     # both alerts posted


def test_gap_straight_through_both_buffers_flattens_immediately():
    g, store, execution, _ = make_guardian(day_start=100_000)
    assert g.on_equity(97_100) == ["hard_flatten"]               # no interim soft-halt
    assert execution.kill_calls == 1
    assert store.state == "KILLED"


def test_kill_fires_exactly_once():
    g, _, execution, _ = make_guardian(day_start=100_000)
    g.on_equity(97_100)
    g.on_equity(96_900)
    g.on_equity(96_500)
    assert execution.kill_calls == 1


def test_static_floor_binds_when_daily_floor_below_it():
    g, store, execution, _ = make_guardian(day_start=96_000)     # 96k-3k=93k < 94k static
    assert g.binding_floor() == 94_000
    assert g.on_equity(94_450) == ["soft_halt"]                  # <= 94,500
    assert g.on_equity(94_150) == ["hard_flatten"]               # <= 94,200
    assert execution.kill_calls == 1


def test_soft_halt_rearms_on_new_day_but_killed_stays():
    g, store, execution, _ = make_guardian(day_start=100_000)
    d1 = datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 7, 8, 0, 5, tzinfo=timezone.utc)

    g.on_equity(97_450, now=d1)
    assert g.soft_halted is True and g.flattened is False

    g.set_day_start(97_400)                                      # new day baseline
    g.on_equity(97_450, now=d2)                                  # rollover happens inside
    assert g.soft_halted is False or g.flattened                 # re-armed since not flattened

    # once flattened, rollover never un-kills
    g2, store2, execution2, _ = make_guardian(day_start=100_000)
    g2.on_equity(97_100, now=d1)
    assert store2.state == "KILLED"
    g2.on_equity(99_000, now=d2)
    assert store2.state == "KILLED"                              # no auto-recovery
    assert execution2.kill_calls == 1


def test_soft_halt_does_not_unpause_manual_states():
    g, store, _, _ = make_guardian(day_start=100_000, state="KILLED")
    g.on_equity(97_450)
    assert store.state == "KILLED"                               # guardian never upgrades state


def test_equity_parser_rejects_missing_balance():
    assert equity_from_account_event({}) is None
    assert equity_from_account_event({"balance": "abc"}) is None
    assert equity_from_account_event(
        {"balance": "100000", "totalUnrealizedPnl": "-250.5", "isolatedPositionMargin": "0"}
    ) == 99_749.5
    # missing optional fields default to 0, but balance is mandatory
    assert equity_from_account_event({"balance": "100000"}) == 100_000.0
