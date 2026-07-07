"""Trade panel acceptance tests: every buy path consults the gate, sells
are reduceOnly, sell-initials math, custom inputs, auth, menu routing."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from risk.gate import GateDecision
from telegram_control import trade_panel
from telegram_control.handlers import ControlServices

ADMIN_ID = 111111
INTRUDER_ID = 999999


class FakeMessage:
    def __init__(self, text=None):
        self.text = text
        self.replies, self.markups = [], []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)
        self.markups.append(reply_markup)


class FakeCallbackQuery:
    def __init__(self, data):
        self.data = data
        self.edits, self.markups = [], []

    async def answer(self):
        pass

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)
        self.markups.append(reply_markup)


class FakeUpdate:
    def __init__(self, user_id, callback_data=None, text=None):
        self.effective_user = type("U", (), {"id": user_id})()
        self.message = FakeMessage(text) if callback_data is None else None
        self.callback_query = FakeCallbackQuery(callback_data) if callback_data else None

    def output(self):
        return "\n".join(self.message.replies if self.message else self.callback_query.edits)


class FakeStore:
    def __init__(self):
        self.market_state = {"ts": None, "symbol": "BTC", "last_price": 60_000.0,
                             "bias": "BULLISH", "long_stop": 59_000.0, "long_target": 62_500.0,
                             "short_stop": None, "short_target": None}
        self.events = []
        self.params = {"risk_pct": 0.0075, "alpha": 1.5, "max_concurrent": 1}

    def get_market_state(self):
        return self.market_state

    def get_strategy_settings(self):
        return {"mode": "production", "active_bias_tf": "4h", "active_trigger_tf": "1h",
                "prod_bias_tf": "4h", "prod_trigger_tf": "1h",
                "test_bias_tf": "5m", "test_trigger_tf": "1m"}

    def get_engine_state(self):
        return "ACTIVE"

    def get_risk_params(self):
        return dict(self.params)

    def record_risk_event(self, event_type, detail=None):
        self.events.append((event_type, detail or {}))


class FakeExecution:
    def __init__(self):
        self.entries, self.closes = [], []
        self.positions = []

    def create_entry_with_bracket(self, **kwargs):
        self.entries.append(kwargs)
        return type("R", (), {"dry_run": True})()

    def get_open_positions(self, base=None):
        return self.positions

    def close_position_market(self, pos, fraction, purpose):
        self.closes.append((pos, fraction, purpose))
        return type("R", (), {"dry_run": True})()


def make_services(gate=None):
    store, execution = FakeStore(), FakeExecution()
    snap = lambda: {"equity": 100_000.0, "peak_equity": 100_000.0,
                    "day_start_equity": 100_000.0, "open_positions_count": 0}
    return ControlServices(store=store, execution=execution, account_snapshot=snap,
                           gate=gate or (lambda *a, **k: GateDecision(
                               approved=True, quantity=0.5, risk_usd=500.0, attenuation_applied=1.0))), store, execution


@pytest.fixture(autouse=True)
def admin_allowlist(monkeypatch):
    monkeypatch.setenv("BTC_SIGNAL_BOT_ADMIN_IDS", str(ADMIN_ID))
    trade_panel.PENDING_INPUTS.clear()


def run(coro):
    return asyncio.run(coro)


# ── layout ──

def test_trade_panel_layout_matches_trojan_spec():
    rows = trade_panel.trade_panel_markup()["inline_keyboard"]
    texts = [[b["text"] for b in row] for row in rows]
    assert texts[0] == ["Buy (risk $500)", "Buy (risk $1000)", "Buy X ✏️"]
    assert texts[1] == ["✅ BTC-PERP"]
    assert texts[2] == ["Sell 50%", "Sell 100%"]
    assert texts[3] == ["Sell Initials", "Sell X% ✏️"]
    assert texts[-1] == ["← Back", "↻ Refresh"]
    # sell buttons reuse the existing Frame B close callbacks (gate-exempt reduceOnly path)
    assert rows[2][0]["callback_data"] == "close_50_BTC"


# ── buys route through the gate ──

def test_preset_buy_consults_gate_and_dispatches_gated_quantity():
    calls = []

    def gate(*a, **k):
        calls.append(k)
        return GateDecision(approved=True, quantity=0.42, risk_usd=420.0, attenuation_applied=0.84)

    services, store, execution = make_services(gate=gate)
    upd = FakeUpdate(ADMIN_ID, callback_data="trd_buy_500")
    run(trade_panel.cb_trade(upd, None, services))

    assert len(calls) == 1
    assert calls[0]["risk_pct"] == pytest.approx(0.005)        # $500 at $100k equity
    assert execution.entries[0]["quantity"] == "0.42"          # gate's quantity, not notional
    assert execution.entries[0]["stop_trigger"] == "59000.0"   # structural level used
    assert ("manual_buy" in [e for e, _ in store.events])
    assert "gated $420.00" in upd.output()


def test_buy_gate_rejection_is_shown_and_nothing_dispatches():
    def gate(*a, **k):
        return GateDecision(approved=False, reasons=["engine state is PAUSED, not ACTIVE"])

    services, _, execution = make_services(gate=gate)
    upd = FakeUpdate(ADMIN_ID, callback_data="trd_buy_1000")
    run(trade_panel.cb_trade(upd, None, services))
    assert execution.entries == []
    assert "Gate rejected" in upd.output()


def test_buy_risk_bounds_enforced():
    services, _, execution = make_services()
    trade_panel.PENDING_INPUTS[ADMIN_ID] = "buy_custom"
    upd = FakeUpdate(ADMIN_ID, text="5000")                    # 5% of 100k — over the 1% max
    run(trade_panel.route_text(upd, None, services))
    assert execution.entries == []
    assert "outside bounds" in upd.output()


def test_buy_without_structural_levels_offers_custom_stop():
    services, store, execution = make_services()
    store.market_state["long_stop"] = None
    upd = FakeUpdate(ADMIN_ID, callback_data="trd_buy_500")
    run(trade_panel.cb_trade(upd, None, services))
    assert execution.entries == []
    assert "Custom" in upd.output() or "custom stop" in upd.output().lower()
    assert upd.callback_query.markups[-1] is not None          # custom-stop submenu offered


def test_custom_stop_buy_satisfies_rr_and_gates():
    calls = []

    def gate(*a, **k):
        calls.append((a, k))
        return GateDecision(approved=True, quantity=0.3, risk_usd=300.0, attenuation_applied=1.0)

    services, _, execution = make_services(gate=gate)
    upd = FakeUpdate(ADMIN_ID, callback_data="trd_cstop_1.0")
    run(trade_panel.cb_trade(upd, None, services))

    assert len(calls) == 1
    signal = calls[0][0][1]                                    # (engine_state, signal)
    assert signal.stop == pytest.approx(60_000 * 0.99)
    assert signal.target == pytest.approx(60_000 * (1 + 0.021))
    assert signal.reward_risk >= 2.0                           # 2.1x construction clears the gate
    assert len(execution.entries) == 1


# ── sells ──

def test_sell_initials_math_and_profit_guard():
    services, _, execution = make_services()
    execution.positions = [{"positionId": "P1", "positionSide": "long", "quantity": "1.0",
                            "base": "BTC", "entryPrice": "60000", "markPrice": "66000"}]
    upd = FakeUpdate(ADMIN_ID, callback_data="trd_sellinit_BTC")
    run(trade_panel.cb_trade(upd, None, services))
    _, fraction, purpose = execution.closes[0]
    assert float(fraction) == pytest.approx(60000 / 66000)     # ~90.9% closes cost basis
    assert purpose == "sell_initials"

    execution.closes.clear()
    execution.positions[0]["markPrice"] = "59000"              # underwater
    upd2 = FakeUpdate(ADMIN_ID, callback_data="trd_sellinit_BTC")
    run(trade_panel.cb_trade(upd2, None, services))
    assert execution.closes == []
    assert "not in profit" in upd2.output()


def test_sell_custom_percent_flow():
    services, _, execution = make_services()
    execution.positions = [{"positionId": "P1", "positionSide": "long", "quantity": "1.0",
                            "base": "BTC", "entryPrice": "60000", "markPrice": "61000"}]
    trade_panel.PENDING_INPUTS[ADMIN_ID] = "sell_custom"
    upd = FakeUpdate(ADMIN_ID, text="37")
    run(trade_panel.route_text(upd, None, services))
    _, fraction, _ = execution.closes[0]
    assert float(fraction) == pytest.approx(0.37)

    trade_panel.PENDING_INPUTS[ADMIN_ID] = "sell_custom"
    upd2 = FakeUpdate(ADMIN_ID, text="150")                    # out of range
    run(trade_panel.route_text(upd2, None, services))
    assert len(execution.closes) == 1                          # unchanged
    assert "1–100" in upd2.output()


# ── auth + menu ──

def test_trade_panel_auth_rejection():
    services, _, execution = make_services()
    upd = FakeUpdate(INTRUDER_ID, callback_data="trd_buy_500")
    run(trade_panel.cb_trade(upd, None, services))
    assert execution.entries == []
    assert upd.output() == ""


def test_kill_from_menu_requires_confirm_step():
    services, _, _ = make_services()
    upd = FakeUpdate(ADMIN_ID, callback_data="menu_kill")
    run(trade_panel.cb_menu(upd, None, services))
    assert "CONFIRM" in str(upd.callback_query.markups[-1])    # confirm step, not immediate kill


def test_persistent_keyboard_routes_to_trade_panel():
    services, _, _ = make_services()
    upd = FakeUpdate(ADMIN_ID, text="\U0001F6D2 Trade")
    run(trade_panel.route_text(upd, None, services))
    assert "TRADE PANEL" in upd.output()
    assert upd.message.markups[-1] is not None
