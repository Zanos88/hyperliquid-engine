"""Acceptance tests for the trend forward test's position rules."""
from __future__ import annotations

from data.feed import Candle
from strategy.trend_rules import sma_positions, tsmom_positions


def _series(prices):
    return [Candle(i, i, p, p, p, p, 0.0) for i, p in enumerate(prices)]


def test_sma_long_in_uptrend_flat_in_downtrend():
    up = _series([100 + i for i in range(60)])
    down = _series([200 - i for i in range(60)])
    assert sma_positions(up, 50)[55] == 1
    assert sma_positions(down, 50)[55] == 0


def test_sma_warmup_is_flat():
    up = _series([100 + i for i in range(60)])
    assert all(p == 0 for p in sma_positions(up, 50)[:49])


def test_tsmom_sign_and_warmup():
    up = _series([100 + i for i in range(60)])
    down = _series([200 - i for i in range(60)])
    assert tsmom_positions(up, 30)[45] == 1
    assert tsmom_positions(down, 30)[45] == 0
    assert all(p == 0 for p in tsmom_positions(up, 30)[:30])


def test_rules_are_causal_prefix_stable():
    # Decisions must not change when future bars are appended.
    prices = [100, 102, 99, 104, 103, 108, 107, 111, 105, 113] * 6
    full = _series(prices)
    for rule, arg in ((sma_positions, 50), (tsmom_positions, 30)):
        full_pos = rule(full, arg)
        prefix_pos = rule(full[:55], arg)
        assert full_pos[:55] == prefix_pos
