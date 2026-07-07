"""Part 1 acceptance tests: timeframes module, engine helpers, /settings UI."""
from __future__ import annotations

import asyncio

import pytest

from strategy.timeframes import (
    INTERVAL_SECONDS,
    PRODUCTION_TIMEFRAMES,
    TEST_TIMEFRAMES,
    interval_seconds,
    validate_combo,
)
from telegram_control import handlers
from telegram_control.handlers import ControlServices

ADMIN_ID = 111111
INTRUDER_ID = 999999


# ── timeframes module ──

def test_production_list_is_native_and_excludes_4d():
    assert PRODUCTION_TIMEFRAMES == ("15m", "30m", "1h", "4h", "8h", "12h", "1d", "3d", "1w")
    assert "4d" not in INTERVAL_SECONDS          # non-native, replaced by 1w per user decision
    assert all(tf in INTERVAL_SECONDS for tf in PRODUCTION_TIMEFRAMES + TEST_TIMEFRAMES)


def test_validate_combo():
    validate_combo("4h", "1h")                    # ok
    validate_combo("1w", "3d")                    # ok
    with pytest.raises(ValueError):
        validate_combo("1h", "4h")                # inverted
    with pytest.raises(ValueError):
        validate_combo("1h", "1h")                # equal
    with pytest.raises(ValueError):
        interval_seconds("4d")                    # unknown interval


# ── engine helpers ──

def test_decorate_labels_mode_and_combo():
    from main import decorate

    prod = {"mode": "production", "active_bias_tf": "4h", "active_trigger_tf": "1h"}
    out = decorate("hello", prod)
    assert "TF: 4h bias / 1h trigger (production)" in out
    assert "[TEST MODE]" not in out

    test = {"mode": "test", "active_bias_tf": "5m", "active_trigger_tf": "1m"}
    out2 = decorate("hello", test)
    assert out2.startswith("\U0001F9EA <b>[TEST MODE]</b>")
    assert "TF: 5m bias / 1m trigger (test)" in out2


def test_data_driven_close_detection():
    from data.feed import Candle
    from main import newest_closed_open_time

    def candle(open_ms):
        return Candle(open_time_ms=open_ms, close_time_ms=open_ms + 3600000,
                      open=1, high=2, low=0.5, close=1.5, volume=10)

    assert newest_closed_open_time([]) is None
    first = [candle(0), candle(3600000)]
    later = [candle(3600000), candle(7200000)]
    a = newest_closed_open_time(first)
    b = newest_closed_open_time(later)
    assert a == 3600000 and b == 7200000 and a != b   # new close detected on change


def test_lookback_scales_with_interval():
    from main import lookback_ms

    assert lookback_ms("1h") == 300 * 3600 * 1000
    assert lookback_ms("15m") == 300 * 900 * 1000
    assert lookback_ms("1w") == 300 * 604800 * 1000


# ── /settings UI (fakes mirror the real store's validation) ──

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


class FakeSettingsStore:
    def __init__(self):
        self.s = {"mode": "production", "prod_bias_tf": "4h", "prod_trigger_tf": "1h",
                  "test_bias_tf": "5m", "test_trigger_tf": "1m"}
        self.events = []

    def get_strategy_settings(self):
        mode = self.s["mode"]
        ab, at = ((self.s["prod_bias_tf"], self.s["prod_trigger_tf"]) if mode == "production"
                  else (self.s["test_bias_tf"], self.s["test_trigger_tf"]))
        return {**self.s, "active_bias_tf": ab, "active_trigger_tf": at}

    def set_strategy_setting(self, name, value, updated_by):
        candidate = {**self.s, name: value}
        if name != "mode":
            validate_combo(candidate["prod_bias_tf"], candidate["prod_trigger_tf"])
            validate_combo(candidate["test_bias_tf"], candidate["test_trigger_tf"])
        old = self.s[name]
        self.s[name] = value
        self.events.append(("settings_change", {"setting": name, "old": old, "new": value}))
        return self.get_strategy_settings()

    def get_engine_state(self):
        return "PAUSED"


def make_services():
    store = FakeSettingsStore()
    return ControlServices(store=store, execution=None, account_snapshot=lambda: {}), store


@pytest.fixture(autouse=True)
def admin_allowlist(monkeypatch):
    monkeypatch.setenv("BTC_SIGNAL_BOT_ADMIN_IDS", str(ADMIN_ID))


def run(coro):
    return asyncio.run(coro)


def test_settings_panel_renders_with_buttons():
    services, _ = make_services()
    upd = FakeUpdate(ADMIN_ID)
    run(handlers.cmd_settings(upd, None, services))
    assert "STRATEGY SETTINGS" in upd.output()
    assert upd.message.markups[-1] is not None      # inline keyboard attached


def test_mode_switch_writes_store():
    services, store = make_services()
    upd = FakeUpdate(ADMIN_ID, callback_data="stg_mode_test")
    run(handlers.cb_settings(upd, None, services))
    assert store.s["mode"] == "test"
    assert "TEST" in upd.output()
    assert ("settings_change" in [e for e, _ in store.events])


def test_timeframe_pick_writes_store():
    services, store = make_services()
    run(handlers.cb_settings(FakeUpdate(ADMIN_ID, "stg_menu_pbias"), None, services))  # open submenu
    upd = FakeUpdate(ADMIN_ID, callback_data="stg_pbias_8h")
    run(handlers.cb_settings(upd, None, services))
    assert store.s["prod_bias_tf"] == "8h"
    assert "8h bias / 1h trigger" in upd.output()


def test_invalid_combo_rejected_with_explanation():
    services, store = make_services()
    upd = FakeUpdate(ADMIN_ID, callback_data="stg_ptrig_1w")   # trigger 1w vs bias 4h -> invalid
    run(handlers.cb_settings(upd, None, services))
    assert store.s["prod_trigger_tf"] == "1h"                  # unchanged
    assert "must be longer than" in upd.output()


def test_test_timeframes_not_reachable_from_production_menus():
    # production submenu only offers PRODUCTION_TIMEFRAMES
    markup = handlers.timeframe_menu_markup("pbias", "4h")
    labels = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
    assert not any(cb.endswith(("_1m", "_3m", "_5m")) for cb in labels if cb.startswith("stg_pbias"))
    # test submenu offers only fast intervals
    markup_t = handlers.timeframe_menu_markup("tbias", "5m")
    tf_cbs = [b["callback_data"] for row in markup_t["inline_keyboard"] for b in row
              if b["callback_data"].startswith("stg_tbias")]
    assert all(cb.split("_")[-1] in TEST_TIMEFRAMES for cb in tf_cbs)


def test_settings_auth_rejection():
    services, store = make_services()
    upd = FakeUpdate(INTRUDER_ID, callback_data="stg_mode_test")
    run(handlers.cb_settings(upd, None, services))
    assert store.s["mode"] == "production"                     # untouched
    assert upd.output() == ""
