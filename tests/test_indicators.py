"""Indicator + dynamic-confluence acceptance tests.

Covers: RSI math (Wilder), Ichimoku components/votes + variants, dynamic
confluence toggle semantics (disabling removes the requirement; enabling
adds it), default-config equivalence with the original 3-indicator
behavior, and the /settings Indicators toggle UI.
"""
from __future__ import annotations

import asyncio

import pytest

from data.feed import Candle
from strategy.ichimoku import VARIANTS, evaluate_ichimoku
from strategy.rsi import Vote, evaluate_rsi, rsi_series
from strategy.signals import DEFAULT_INDICATOR_CONFIG, INDICATOR_NAMES, evaluate_confluence
from telegram_control import handlers
from telegram_control.handlers import ControlServices

ADMIN_ID = 111111


def make_candle(i, close, high=None, low=None, volume=100.0):
    return Candle(open_time_ms=i * 3600000, close_time_ms=(i + 1) * 3600000,
                  open=close, high=high if high is not None else close + 10,
                  low=low if low is not None else close - 10, close=close, volume=volume)


def trending_candles(n, start=60_000.0, step=50.0):
    return [make_candle(i, start + i * step) for i in range(n)]


# ── RSI ──

def test_rsi_all_gains_is_100_and_votes_long():
    candles = trending_candles(20, step=100.0)          # monotonic up
    reading = evaluate_rsi(candles)
    assert reading.value == pytest.approx(100.0)
    assert reading.vote == Vote.LONG


def test_rsi_all_losses_votes_short():
    candles = trending_candles(20, step=-100.0)
    reading = evaluate_rsi(candles)
    assert reading.value == pytest.approx(0.0)
    assert reading.vote == Vote.SHORT


def test_rsi_insufficient_history_votes_none():
    assert evaluate_rsi(trending_candles(10)).vote == Vote.NONE


def test_rsi_known_alternating_value():
    # Alternating +100/-50 deltas: simple-average RSI would be ~66.67; the
    # Wilder-smoothed value oscillates around it by last-delta sign — here
    # the final delta is a loss, so the lower branch (~64.4) is correct.
    closes, price = [], 60_000.0
    for i in range(30):
        price += 100.0 if i % 2 == 0 else -50.0
        closes.append(price)
    candles = [make_candle(i, c) for i, c in enumerate(closes)]
    reading = evaluate_rsi(candles)
    assert 60.0 < reading.value < 68.0                  # bullish regime, Wilder-smoothed
    assert reading.value == pytest.approx(64.44, abs=0.5)
    assert reading.vote == Vote.LONG


# ── Ichimoku ──

def test_ichimoku_uptrend_votes_long_downtrend_short():
    up = trending_candles(120, step=100.0)
    down = trending_candles(120, step=-100.0)
    assert evaluate_ichimoku(up).vote == Vote.LONG      # price above cloud, tenkan>kijun
    assert evaluate_ichimoku(down).vote == Vote.SHORT


def test_ichimoku_insufficient_history_none():
    assert evaluate_ichimoku(trending_candles(40)).vote == Vote.NONE   # needs 52+26 std


def test_ichimoku_variants():
    up = trending_candles(120, step=100.0)
    std = evaluate_ichimoku(up, variant="standard")
    crypto = evaluate_ichimoku(up, variant="crypto")
    assert std.variant == "standard" and crypto.variant == "crypto"
    assert VARIANTS["crypto"] == (10, 30, 60)
    assert std.tenkan != crypto.tenkan                  # different windows -> different lines
    with pytest.raises(ValueError):
        evaluate_ichimoku(up, variant="weekend")


# ── dynamic confluence ──

def _steady(n=120):
    """Sideways series: bias NEUTRAL, no fisher cross — baseline no-signal."""
    return [make_candle(i, 60_000 + (i % 3) * 20) for i in range(n)]


def test_default_config_matches_original_three_indicator_behavior():
    c_bias, c_trig = _steady(), _steady()
    d_default, readings, _ = evaluate_confluence(c_bias, c_trig)          # config=None
    d_explicit, _, _ = evaluate_confluence(c_bias, c_trig, config=DEFAULT_INDICATOR_CONFIG)
    assert d_default == d_explicit
    assert set(readings.keys()) == set(INDICATOR_NAMES)
    assert readings["rsi"]["enabled"] is False and readings["ichimoku"]["enabled"] is False


def test_enabling_an_indicator_adds_requirement():
    # Uptrend: rsi LONG + ichimoku LONG, but fisher only votes on cross bars.
    up = trending_candles(120, step=100.0)
    cfg_rsi_only = {n: False for n in INDICATOR_NAMES} | {"rsi": True}
    d, readings, _ = evaluate_confluence(up, up, config=cfg_rsi_only)
    assert d is not None and d.value == "LONG"          # rsi alone -> aligned LONG

    cfg_rsi_fisher = cfg_rsi_only | {"fisher": True}
    d2, readings2, _ = evaluate_confluence(up, up, config=cfg_rsi_fisher)
    if readings2["fisher"]["vote"] == "NONE":           # no cross this bar (typical)
        assert d2 is None                               # fisher requirement now blocks


def test_disabling_removes_requirement_not_forces_pass():
    up = trending_candles(120, step=100.0)
    all_on = {n: True for n in INDICATOR_NAMES}
    d_all, readings_all, _ = evaluate_confluence(up, up, config=all_on)

    no_fisher = all_on | {"fisher": False}
    d_nf, readings_nf, _ = evaluate_confluence(up, up, config=no_fisher)
    # with fisher's NONE vote removed, remaining LONG votes can align
    remaining = [r["vote"] for n, r in readings_nf.items() if no_fisher[n]]
    if all(v == "LONG" for v in remaining):
        assert d_nf is not None and d_nf.value == "LONG"
    # readings still computed for disabled indicators (snapshot completeness)
    assert readings_nf["fisher"]["vote"] in ("LONG", "SHORT", "NONE")


def test_nothing_enabled_never_signals():
    up = trending_candles(120, step=100.0)
    none_on = {n: False for n in INDICATOR_NAMES}
    d, _, _ = evaluate_confluence(up, up, config=none_on)
    assert d is None


# ── toggle UI ──

class FakeMessage:
    def __init__(self):
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
    def __init__(self, user_id, callback_data=None):
        self.effective_user = type("U", (), {"id": user_id})()
        self.message = FakeMessage() if callback_data is None else None
        self.callback_query = FakeCallbackQuery(callback_data) if callback_data else None

    def output(self):
        return "\n".join(self.message.replies if self.message else self.callback_query.edits)


class FakeIndicatorStore:
    def __init__(self):
        self.cfg = dict(DEFAULT_INDICATOR_CONFIG) | {"ichimoku_variant": "standard"}
        self.events = []

    def get_indicator_config(self):
        return dict(self.cfg)

    def set_indicator_toggle(self, name, enabled, updated_by):
        candidate = {**self.cfg, name: enabled}
        if not any(candidate[n] for n in INDICATOR_NAMES):
            raise ValueError("at least one indicator must remain enabled")
        self.cfg[name] = enabled
        self.events.append(("settings_change", name))
        return dict(self.cfg)

    def set_ichimoku_variant(self, variant, updated_by):
        self.cfg["ichimoku_variant"] = variant
        return dict(self.cfg)

    def get_strategy_settings(self):
        return {"mode": "production", "prod_bias_tf": "4h", "prod_trigger_tf": "1h",
                "test_bias_tf": "5m", "test_trigger_tf": "1m",
                "active_bias_tf": "4h", "active_trigger_tf": "1h"}

    def get_risk_params(self):
        return {"risk_pct": 0.0075, "alpha": 1.5, "max_concurrent": 1}


def make_services():
    store = FakeIndicatorStore()
    return ControlServices(store=store, execution=None, account_snapshot=lambda: {}), store


@pytest.fixture(autouse=True)
def admin_allowlist(monkeypatch):
    monkeypatch.setenv("BTC_SIGNAL_BOT_ADMIN_IDS", str(ADMIN_ID))


def run(coro):
    return asyncio.run(coro)


def test_indicator_toggle_flips_state_and_updates_summary():
    services, store = make_services()
    upd = FakeUpdate(ADMIN_ID, callback_data="stg_ind_rsi")
    run(handlers.cb_settings(upd, None, services))
    assert store.cfg["rsi"] is True
    assert "RSI" in upd.output() and "Active:" in upd.output()

    upd2 = FakeUpdate(ADMIN_ID, callback_data="stg_ind_fisher")   # disable fisher
    run(handlers.cb_settings(upd2, None, services))
    assert store.cfg["fisher"] is False
    assert "Fisher off" in upd2.output() or "(Fisher" in upd2.output()


def test_cannot_disable_last_indicator():
    services, store = make_services()
    for name in ("bias_sr", "fisher"):                  # leave only obv on
        run(handlers.cb_settings(FakeUpdate(ADMIN_ID, f"stg_ind_{name}"), None, services))
    upd = FakeUpdate(ADMIN_ID, callback_data="stg_ind_obv")
    run(handlers.cb_settings(upd, None, services))
    assert store.cfg["obv"] is True                      # refused
    assert "at least one" in upd.output()


def test_ichimoku_variant_toggle():
    services, store = make_services()
    upd = FakeUpdate(ADMIN_ID, callback_data="stg_indvar_crypto")
    run(handlers.cb_settings(upd, None, services))
    assert store.cfg["ichimoku_variant"] == "crypto"


def test_indicator_summary_format():
    cfg = dict(DEFAULT_INDICATOR_CONFIG) | {"ichimoku_variant": "standard"}
    line = handlers.indicator_summary(cfg)
    assert line.startswith("Active: Bias (S/R+Fib)+Fisher+OBV")
    assert "RSI" in line and "Ichimoku" in line and "off" in line


def test_indicators_button_present_in_settings_menu():
    markup = handlers.settings_menu_markup({"mode": "production"})
    cbs = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
    assert "stg_menu_ind" in cbs
