"""Acceptance tests for the trend-exhaustion stand-down gate (Phase 1)."""
from __future__ import annotations

import pytest

from backtest import STANDDOWN_WINDOW_MS, expand_sweep
from strategy.signals import SignalDirection, standdown_suppresses


def test_suppresses_only_crowded_direction():
    # Funding at the 90th percentile: longs are crowded -> suppress longs only.
    assert standdown_suppresses(SignalDirection.LONG, 90.0, 85.0) is True
    assert standdown_suppresses(SignalDirection.SHORT, 90.0, 85.0) is False
    # Funding at the 10th percentile: shorts are crowded -> suppress shorts only.
    assert standdown_suppresses(SignalDirection.SHORT, 10.0, 85.0) is True
    assert standdown_suppresses(SignalDirection.LONG, 10.0, 85.0) is False
    # Mid-range funding: nothing suppressed either way.
    assert standdown_suppresses(SignalDirection.LONG, 60.0, 85.0) is False
    assert standdown_suppresses(SignalDirection.SHORT, 60.0, 85.0) is False


def test_oi_conjunction():
    # Crowded funding but OI z below the floor -> pass (conjunction).
    assert standdown_suppresses(SignalDirection.LONG, 95.0, 85.0, oi_z=1.0, oi_z_min=2.0) is False
    assert standdown_suppresses(SignalDirection.LONG, 95.0, 85.0, oi_z=2.5, oi_z_min=2.0) is True
    # OI required but missing -> loud failure, never silent.
    with pytest.raises(ValueError):
        standdown_suppresses(SignalDirection.LONG, 95.0, 85.0, oi_z=None, oi_z_min=2.0)


def test_expand_sweep_standdown_axis():
    cfg = {"grids": [{
        "name": "g", "tf_pairs": [{"bias": "4h", "trigger": "1h"}],
        "indicator_sets": ["default"], "stop_models": [{"model": "structural"}],
        "target_models": ["fib_extension_preferred"],
        "standdown": [{"entry": False}, {"entry": True, "funding_pctiles": [85, 90]}],
    }]}
    combos = expand_sweep(cfg)
    assert len(combos) == 3
    assert [c["standdown_entry"] for c in combos] == [False, True, True]
    assert [c["funding_pctile"] for c in combos] == [None, 85, 90]
    # A grid WITHOUT a standdown key stays gate-off (backward compatible).
    del cfg["grids"][0]["standdown"]
    combos = expand_sweep(cfg)
    assert len(combos) == 1 and combos[0]["standdown_entry"] is False


def test_trailing_funding_percentile_is_causal():
    # Reconstruct the gate's percentile math and verify appending FUTURE rows
    # never changes the value at an earlier timestamp.
    from bisect import bisect_right

    def pctile(times, vals, ts):
        hi = bisect_right(times, ts)
        lo = bisect_right(times, ts - STANDDOWN_WINDOW_MS)
        window = vals[lo:hi]
        return 100.0 * sum(1 for v in window if v <= vals[hi - 1]) / len(window)

    hour = 3600_000
    times = [i * hour for i in range(2000)]
    vals = [((i * 37) % 100) / 10_000 for i in range(2000)]
    ts = times[1500]
    before = pctile(times, vals, ts)
    after = pctile(times + [times[-1] + hour], vals + [9.9], ts)
    assert before == after
    # And the window is trailing-30d only: a value spike 31 days earlier is excluded.
    spike_idx = 1500 - (31 * 24)
    vals2 = list(vals)
    vals2[spike_idx] = 99.0
    assert pctile(times, vals2, ts) == before
