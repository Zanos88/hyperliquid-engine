"""Severity-tier acceptance tests: silent delivery plumbing, tier tags in
every header, regime-shift formatter WHY content."""
from __future__ import annotations

from datetime import datetime, timezone

from alerts.formats import (
    format_daily_summary,
    format_entry_signal,
    format_exit_alert,
    format_halt_alert,
    format_heartbeat,
    format_regime_shift,
)
from ledger.tracker import ClosedPosition
from strategy.signals import Signal, SignalDirection

NOW = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)


def make_signal():
    return Signal(direction=SignalDirection.LONG, entry=61_780.0, stop=60_900.0,
                  target=63_600.0, reward_risk=2.07, timestamp=NOW,
                  bias_reason="r", trigger_reason="t")


# ── silent flag reaches the Bot API payload ──

def test_send_passes_disable_notification(monkeypatch):
    import alerts.telegram as tg

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        return FakeResp()

    monkeypatch.setattr(tg.requests, "post", fake_post)
    client = tg.TelegramClient(bot_token="t", chat_id="c")

    client.send("loud alert")
    assert "disable_notification" not in captured   # T3+ default: notify

    captured.clear()
    client.send("quiet update", silent=True)
    assert captured.get("disable_notification") is True   # T1/T2: silent


# ── tier tags present in every header ──

def test_tier_tags_in_headers():
    ctx = {"equity": 100_000.0, "day_start_equity": 100_000.0}
    assert "[T3 SETUP]" in format_entry_signal(make_signal(), 0.85, 0.0075, 750.0)

    closed = ClosedPosition(signal=make_signal(), quantity=0.85, opened_at=NOW, closed_at=NOW,
                            exit_price=63_600.0, exit_reason="target", pnl=1_547.0, pnl_r=2.07)
    assert "[T4 RISK]" in format_exit_alert(closed, 1_547.0)

    assert "[T5 HALT]" in format_halt_alert(-0.026, context=ctx)
    assert "[T2] HEARTBEAT" in format_heartbeat("BULLISH", NOW, 0)
    stats = {"signals_fired": 0, "closed_trades": 0, "wins": 0, "win_rate": None,
             "daily_pnl": 0.0, "daily_pnl_pct": 0.0, "equity": 100_000.0}
    assert "[T2] DAILY SUMMARY" in format_daily_summary(stats, "NEUTRAL", 0)


# ── regime shift states the WHY ──

def test_regime_shift_states_exact_level():
    text = format_regime_shift(
        "NEUTRAL", "BULLISH",
        "price 61,780.00 above 0.618 retrace 61,320.00 and holding support",
        61_780.0,
        context={"equity": 100_000.0, "day_start_equity": 100_000.0,
                 "levels": {"long_stop": 60_900.0, "long_target": 63_600.0,
                            "short_stop": None, "short_target": None}},
    )
    assert "[T2 REGIME] BIAS SHIFT: NEUTRAL → BULLISH" in text
    assert "Why: price 61,780.00 above 0.618 retrace 61,320.00" in text   # exact level
    assert "Structural long now: stop $60,900 / target $63,600" in text
    assert "left before daily breach" in text
