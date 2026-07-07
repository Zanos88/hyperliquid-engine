"""Structured alert format acceptance tests (2026-07-07 redesign):
explicit BUY/SELL, four sections, reasoning with actual reading values,
floor distances, WHY-state heartbeat, /testalert rendering."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from alerts.formats import (
    format_daily_summary,
    format_entry_signal,
    format_exit_alert,
    format_halt_alert,
    format_heartbeat,
)
from ledger.tracker import ClosedPosition
from strategy.signals import Signal, SignalDirection

NOW = datetime(2026, 7, 7, 23, 41, tzinfo=timezone.utc)

READINGS = {
    "bias_sr": {"enabled": True, "vote": "LONG", "bias": "BULLISH",
                "reason": "price 61,780.00 above 0.618 retrace 61,320.00 and holding support"},
    "fisher": {"enabled": True, "vote": "LONG", "cross": "bullish", "value": 1.24},
    "obv": {"enabled": True, "vote": "LONG", "state": "rising", "value": 15234.5},
    "rsi": {"enabled": False, "vote": "LONG", "value": 57.3},
    "ichimoku": {"enabled": False, "vote": "NONE", "tenkan": 61650.0, "kijun": 61400.0,
                 "senkou_a": 61200.0, "senkou_b": 60900.0, "variant": "standard"},
}

CTX = {"trigger_tf": "1h", "bias_tf": "4h", "readings": READINGS,
       "equity": 100_000.0, "day_start_equity": 100_000.0,
       "open_positions": 0, "position_line": "none", "attenuation": 1.0}


def long_signal(entry=61_780.0, stop=60_900.0, target=63_600.0):
    return Signal(direction=SignalDirection.LONG, entry=entry, stop=stop, target=target,
                  reward_risk=(target - entry) / (entry - stop), timestamp=NOW,
                  bias_reason="r", trigger_reason="t")


def short_signal():
    return Signal(direction=SignalDirection.SHORT, entry=61_780.0, stop=62_600.0,
                  target=59_900.0, reward_risk=2.29, timestamp=NOW,
                  bias_reason="r", trigger_reason="t")


def test_entry_states_buy_explicitly_for_long():
    text = format_entry_signal(long_signal(), 0.85, 0.0075, 750.0, context=CTX)
    assert "BUY BTC-PERP (LONG)" in text
    assert "SELL" not in text.split("\n")[0]


def test_entry_states_sell_explicitly_for_short():
    text = format_entry_signal(short_signal(), 0.85, 0.0075, 750.0, context=CTX)
    assert "SELL BTC-PERP (SHORT)" in text


def test_entry_has_all_four_sections():
    text = format_entry_signal(long_signal(), 0.85, 0.0075, 750.0, context=CTX)
    for section in ("── Direction", "── Reasoning", "── Position Context", "── Risk"):
        assert section in text, f"missing section {section}"


def test_entry_reasoning_cites_actual_values():
    text = format_entry_signal(long_signal(), 0.85, 0.0075, 750.0, context=CTX)
    assert "Bias (4h): BULLISH — price 61,780.00 above 0.618 retrace" in text
    assert "Fisher (1h): bullish cross (value 1.24)" in text
    assert "OBV (1h): rising" in text
    assert "Off: rsi, ichimoku" in text          # disabled listed, not faked


def test_entry_risk_section_has_floors_and_attenuation():
    text = format_entry_signal(long_signal(), 0.85, 0.0075, 750.0, context=CTX)
    assert "daily $97,000 ($3,000 away)" in text
    assert "static $94,000 ($6,000 away)" in text
    assert "attenuation 1.000" in text
    assert "structural" in text                   # stop labeled structural
    assert "no hyperliquid" not in text.lower() and "hyperliquid" not in text.lower()


def test_entry_without_context_degrades_gracefully():
    text = format_entry_signal(long_signal(), 0.85, 0.0075, 750.0)
    assert "BUY BTC-PERP (LONG)" in text
    assert "── Risk" in text                      # risk always present
    assert "── Reasoning" not in text             # omitted, never faked


def test_exit_states_closing_action():
    closed = ClosedPosition(signal=long_signal(), quantity=0.85, opened_at=NOW, closed_at=NOW,
                            exit_price=63_600.0, exit_reason="target", pnl=1_547.0, pnl_r=2.07)
    text = format_exit_alert(closed, 1_547.0, context={**CTX, "equity": 101_547.0})
    assert "CLOSED LONG (SELL) — TARGET HIT" in text
    assert "+2.07R" in text and "$+1,547.00" in text
    assert "away)" in text                        # floor distances present

    closed_s = ClosedPosition(signal=short_signal(), quantity=0.85, opened_at=NOW, closed_at=NOW,
                              exit_price=62_600.0, exit_reason="stop", pnl=-700.0, pnl_r=-1.0)
    text_s = format_exit_alert(closed_s, -700.0, context=CTX)
    assert "CLOSED SHORT (BUY) — STOP HIT" in text_s


def test_heartbeat_is_why_snapshot():
    ctx = {**CTX, "last_price": 61_780.0,
           "levels": {"long_stop": 60_900.0, "long_target": 63_600.0,
                      "short_stop": None, "short_target": None}}
    text = format_heartbeat("BULLISH", NOW, 0, context=ctx)
    assert "Structural long setup: stop $60,900 / target $63,600" in text
    assert "R:R 2.1" in text
    assert "Fisher (1h): bullish cross" in text   # last readings surfaced
    assert "away)" in text                        # floor distances
    assert "feed errors since last heartbeat: 0" in text


def test_halt_shows_numbers():
    ctx = {**CTX, "equity": 97_400.0}
    text = format_halt_alert(-0.026, context=ctx)
    assert "-2.60%" in text
    assert "Equity $97,400.00" in text
    assert "away)" in text


def test_daily_summary_shows_equity_curve():
    stats = {"signals_fired": 3, "closed_trades": 2, "wins": 1, "win_rate": 0.5,
             "daily_pnl": 850.0, "daily_pnl_pct": 0.0085, "equity": 100_850.0}
    text = format_daily_summary(stats, "BULLISH", 0)
    assert "$100,000.00 → $100,850.00" in text
    assert "Win rate: 50%" in text


# ── /testalert renders through the real formatters ──

def test_testalert_command(monkeypatch):
    monkeypatch.setenv("BTC_SIGNAL_BOT_ADMIN_IDS", "111111")
    from telegram_control import handlers
    from telegram_control.handlers import ControlServices

    class FakeMessage:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text, reply_markup=None):
            self.replies.append(text)

    class FakeUpdate:
        def __init__(self, uid):
            self.effective_user = type("U", (), {"id": uid})()
            self.message = FakeMessage()
            self.callback_query = None

    services = ControlServices(store=None, execution=None, account_snapshot=lambda: {})
    upd = FakeUpdate(111111)
    asyncio.run(handlers.cmd_testalert(upd, None, services))

    joined = "\n\n".join(upd.message.replies)
    assert "SYNTHETIC" in joined
    assert "BUY BTC-PERP (LONG)" in joined
    assert "── Reasoning" in joined
    assert "CLOSED LONG (SELL)" in joined

    intruder = FakeUpdate(999999)
    asyncio.run(handlers.cmd_testalert(intruder, None, services))
    assert intruder.message.replies == []
