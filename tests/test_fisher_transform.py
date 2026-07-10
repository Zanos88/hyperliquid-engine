"""Regression tests for the Fisher Transform fix (2026-07-10).

The original implementation applied Ehlers' x2 scaling twice
(`0.33 * 2 * raw` with raw already spanning [-1, 1]), giving the smoothing
recursion a gain of 1.33 > 1 — x pegged at the +/-0.999 clamp during any
sustained move and Fisher saturated toward its recursive ceiling (~7.6).
Measured on the frozen BTC snapshots, the buggy version put |F| >= 2 on
43-47% of bars (max 7.60); the corrected version puts it on 0.0-0.2%
(max 2.04-2.21) — matching real-world Fisher behavior (extremes rare,
4-5 effectively never). These tests pin that distribution.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from data.feed import Candle
from strategy.trigger_1h import fisher_transform

REPO = Path(__file__).resolve().parents[1]


def _flat(prices):
    return [Candle(i, i, p, p, p, p, 0.0) for i, p in enumerate(prices)]


def test_clamp_increment_invariant_on_pegged_ramp():
    # A monotone ramp with H == L pegs raw at +1 — the worst case. Even
    # there, each bar's contribution is bounded by the 0.999 clamp:
    # |f[i] - 0.5 * f[i-1]| <= 0.5 * ln(1.999/0.001) ~= 3.80.
    candles = _flat([100 + i for i in range(400)])
    f, _ = fisher_transform(candles)
    cap = 0.5 * math.log(1.999 / 0.001) + 1e-9
    assert all(abs(f[i] - 0.5 * f[i - 1]) <= cap for i in range(1, len(f)))
    # And the recursive ceiling is the only thing approached — never exceeded.
    assert max(abs(v) for v in f) <= 2 * cap


def test_realistic_series_stays_out_of_saturation():
    # Seeded random-walk with real H/L spread: the corrected recursion
    # (gain 1.0) must stay far below the buggy saturation regime (>5).
    rng = random.Random(7)
    candles = []
    px = 100.0
    for i in range(3000):
        px *= math.exp(rng.gauss(0, 0.01))
        hi = px * (1 + abs(rng.gauss(0, 0.004)))
        lo = px * (1 - abs(rng.gauss(0, 0.004)))
        candles.append(Candle(i, i, px, hi, lo, px, 0.0))
    f, _ = fisher_transform(candles)
    # Corrected recursion measures 3.29 on this seeded series (synthetic
    # H/L spreads are narrower than real bars, so raw pegs more easily);
    # the buggy 1.33-gain recursion saturates to ~7.5 on the SAME series.
    # 5.0 separates the regimes cleanly.
    assert max(abs(v) for v in f) < 5.0


def test_prefix_stability_causal():
    rng = random.Random(11)
    prices = [100.0]
    for _ in range(300):
        prices.append(prices[-1] * math.exp(rng.gauss(0, 0.01)))
    candles = _flat(prices)
    full, _ = fisher_transform(candles)
    prefix, _ = fisher_transform(candles[:200])
    assert full[:200] == prefix


@pytest.mark.parametrize("tf,max_bound", [("1h", 2.5), ("4h", 2.5)])
def test_real_data_distribution_pinned(tf, max_bound):
    # Frozen snapshots -> deterministic. Bounds pinned just above the
    # measured corrected values (1h: max 2.04 / p99 1.71; 4h: 2.21 / 1.78).
    # The buggy implementation measures max 7.60 / p99 ~7.6 / |F|>=2 on
    # 43-47% of bars on the SAME data — this test fails loudly on it.
    snap = REPO / "research" / "data" / f"BTC_{tf}_snapshot.json"
    if not snap.exists():
        pytest.skip(f"frozen snapshot missing: {snap}")
    doc = json.loads(snap.read_text(encoding="utf-8"))
    candles = [Candle(*row) for row in doc["candles"]]
    f, _ = fisher_transform(candles)
    vals = [abs(v) for v in f[20:]]
    vals_sorted = sorted(vals)
    p99 = vals_sorted[math.ceil(0.99 * len(vals_sorted)) - 1]
    share_ge2 = sum(1 for v in vals if v >= 2) / len(vals)
    share_ge3 = sum(1 for v in vals if v >= 3) / len(vals)
    assert max(vals) < max_bound
    assert p99 < 2.0
    assert share_ge2 < 0.01      # extremes are rare (measured 0.0-0.2%)
    assert share_ge3 == 0.0      # 3+ never happens on 2020-2026 BTC data
