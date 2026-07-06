from datetime import datetime, timezone

import pytest

from ledger.tracker import Ledger
from strategy.signals import Signal, SignalDirection


def make_signal(direction, entry, stop, target):
    return Signal(
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        reward_risk=abs(target - entry) / abs(entry - stop),
        timestamp=datetime.now(timezone.utc),
        bias_reason="test",
        trigger_reason="test",
    )


def make_ledger(equity=100_000):
    return Ledger(starting_equity=equity, equity=equity, day_start_equity=equity)


def test_open_position_computes_quantity():
    ledger = make_ledger()
    sig = make_signal(SignalDirection.LONG, entry=60_000, stop=59_000, target=62_000)
    pos = ledger.open_hypothetical_position(sig, risk_pct=0.0075, sz_decimals=5)
    assert pos.quantity == pytest.approx(0.75, abs=1e-5)
    assert len(ledger.open_positions) == 1


def test_long_position_hits_target():
    ledger = make_ledger()
    sig = make_signal(SignalDirection.LONG, entry=60_000, stop=59_000, target=62_000)
    ledger.open_hypothetical_position(sig, risk_pct=0.0075, sz_decimals=5)

    closed = ledger.check_exits(current_price=62_500)
    assert len(closed) == 1
    assert closed[0].exit_reason == "target"
    assert closed[0].pnl > 0
    assert len(ledger.open_positions) == 0
    assert ledger.equity > ledger.starting_equity


def test_long_position_hits_stop():
    ledger = make_ledger()
    sig = make_signal(SignalDirection.LONG, entry=60_000, stop=59_000, target=62_000)
    ledger.open_hypothetical_position(sig, risk_pct=0.0075, sz_decimals=5)

    closed = ledger.check_exits(current_price=58_900)
    assert closed[0].exit_reason == "stop"
    assert closed[0].pnl < 0
    assert closed[0].pnl_r == pytest.approx(-1.0, abs=1e-3)


def test_short_position_hits_target():
    ledger = make_ledger()
    sig = make_signal(SignalDirection.SHORT, entry=60_000, stop=61_000, target=58_000)
    ledger.open_hypothetical_position(sig, risk_pct=0.0075, sz_decimals=5)

    closed = ledger.check_exits(current_price=57_500)
    assert closed[0].exit_reason == "target"
    assert closed[0].pnl > 0


def test_open_position_not_closed_when_price_between_stop_and_target():
    ledger = make_ledger()
    sig = make_signal(SignalDirection.LONG, entry=60_000, stop=59_000, target=62_000)
    ledger.open_hypothetical_position(sig, risk_pct=0.0075, sz_decimals=5)

    closed = ledger.check_exits(current_price=60_500)
    assert closed == []
    assert len(ledger.open_positions) == 1


def test_daily_pnl_and_new_day_reset():
    ledger = make_ledger()
    sig = make_signal(SignalDirection.LONG, entry=60_000, stop=59_000, target=62_000)
    ledger.open_hypothetical_position(sig, risk_pct=0.0075, sz_decimals=5)
    ledger.check_exits(current_price=62_500)

    assert ledger.daily_pnl() > 0
    stats = ledger.today_stats()
    assert stats["closed_trades"] == 1
    assert stats["wins"] == 1

    ledger.start_new_day()
    assert ledger.day_start_equity == ledger.equity
    assert ledger.daily_pnl() == 0
    assert ledger.closed_today == []
