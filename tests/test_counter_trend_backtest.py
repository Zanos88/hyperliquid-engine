"""simulate_counter_trend_outcome: fixed stop vs DYNAMIC opposite-cloud
target (recomputed each bar), stop-first ambiguity, fee math, unresolved,
and that the target is read per-bar (no lookahead). The cloud is mocked
so the moving target is deterministic."""
from __future__ import annotations

import pathlib

import pytest
import yaml

import strategy.counter_trend as ct
from backtest import TAKER_FEE, simulate_counter_trend_outcome
from data.feed import Candle
from strategy.counter_trend import CounterTrendSignal

H = 3600000


def candle(i, close, high, low, vol=100.0):
    return Candle(open_time_ms=i * H, close_time_ms=(i + 1) * H,
                  open=close, high=high, low=low, close=close, volume=vol)


def long_signal(entry=100.0, stop=95.0, target=110.0):
    return CounterTrendSignal(direction="LONG", entry=entry, stop=stop, target_at_entry=target,
                              reward_risk=(target - entry) / (entry - stop), fisher_value=-2.5,
                              obv_rule="divergence", reason="t")


def patch_cloud(monkeypatch, top_by_bar: dict, bottom_by_bar: dict):
    """ichimoku_components keyed to the window's last bar index, so the
    cloud (and thus the dynamic target) can differ bar-to-bar."""
    def fake(window, variant="standard"):
        idx = window[-1].open_time_ms // H
        return (0.0, 0.0, top_by_bar.get(idx), bottom_by_bar.get(idx))
    monkeypatch.setattr(ct, "ichimoku_components", fake)


def test_long_target_touch_two_r_minus_fees(monkeypatch):
    patch_cloud(monkeypatch, {1: 110.0, 2: 110.0}, {1: 90.0, 2: 90.0})
    candles = [candle(0, 100, 101, 99), candle(1, 102, 105, 98), candle(2, 108, 115, 107)]
    t = simulate_counter_trend_outcome(candles, 0, long_signal())
    assert t.exit_reason == "target"
    assert t.gross_r == pytest.approx(2.0)                 # (110-100)/5
    assert t.net_r == pytest.approx(2.0 - (100 + 110) * TAKER_FEE / 5)
    assert t.bars_held == 2


def test_long_stop_touch_minus_one_r(monkeypatch):
    patch_cloud(monkeypatch, {1: 110.0}, {1: 90.0})
    candles = [candle(0, 100, 101, 99), candle(1, 98, 102, 94)]   # low 94 <= stop 95
    t = simulate_counter_trend_outcome(candles, 0, long_signal())
    assert t.exit_reason == "stop"
    assert t.gross_r == pytest.approx(-1.0)
    assert t.net_r < -1.0


def test_ambiguous_bar_is_stop_first(monkeypatch):
    patch_cloud(monkeypatch, {1: 110.0}, {1: 90.0})
    candles = [candle(0, 100, 101, 99), candle(1, 100, 120, 90)]  # touches stop 95 AND target 110
    t = simulate_counter_trend_outcome(candles, 0, long_signal())
    assert t.exit_reason == "stop"


def test_dynamic_target_moves_with_cloud(monkeypatch):
    # same 115 high on both bars; bar1 target 120 (miss), bar2 target drops
    # to 110 (hit) -> proves the target is recomputed per bar, not fixed,
    # and read from that bar's window only (no lookahead to bar2 at bar1).
    patch_cloud(monkeypatch, {1: 120.0, 2: 110.0}, {1: 90.0, 2: 90.0})
    candles = [candle(0, 100, 101, 99), candle(1, 105, 115, 98), candle(2, 105, 115, 98)]
    t = simulate_counter_trend_outcome(candles, 0, long_signal())
    assert t.exit_reason == "target"
    assert t.bars_held == 2                                # not 1 — bar1's target was 120


def test_short_mirrored(monkeypatch):
    patch_cloud(monkeypatch, {1: 115.0, 2: 115.0}, {1: 90.0, 2: 90.0})
    sig = CounterTrendSignal(direction="SHORT", entry=100.0, stop=105.0, target_at_entry=90.0,
                             reward_risk=2.0, fisher_value=2.5, obv_rule="divergence", reason="t")
    candles = [candle(0, 100, 101, 99), candle(1, 95, 101, 98), candle(2, 92, 99, 89)]  # low 89<=90
    t = simulate_counter_trend_outcome(candles, 0, sig)
    assert t.exit_reason == "target"
    assert t.gross_r == pytest.approx(2.0)                 # (100-90)/5


def test_unresolved_when_never_touched(monkeypatch):
    patch_cloud(monkeypatch, {1: 110.0, 2: 110.0}, {1: 90.0, 2: 90.0})
    candles = [candle(0, 100, 101, 99), candle(1, 100, 103, 97), candle(2, 100, 104, 96)]
    t = simulate_counter_trend_outcome(candles, 0, long_signal())
    assert t.exit_reason == "unresolved"
    assert t.gross_r is None and t.net_r is None


def test_shipped_counter_trend_sweep_config():
    path = pathlib.Path(__file__).resolve().parent.parent / "sweep_counter_trend.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert cfg["strategy"] == "counter_trend"
    combos = len(cfg["fisher_tfs"]) * len(cfg["obv_rules"]) * len(cfg["exhaustion_thresholds"])
    assert combos == 12
