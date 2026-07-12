"""Unit tests for the order-book snapshot logger (pure functions, no network)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from orderbook_logger import HOUR_MS, MAX_LAG_MS, boundary_ok, top_n_imbalance


def _book(bids, asks):
    return [[{"px": "100", "sz": str(s), "n": 1} for s in bids],
            [{"px": "101", "sz": str(s), "n": 1} for s in asks]]


def test_imbalance_matches_locked_definition():
    imb, bid, ask = top_n_imbalance(_book([3.0] * 10, [1.0] * 10))
    assert bid == 30.0 and ask == 10.0
    assert imb == pytest.approx((30 - 10) / 40)  # +0.5, bid-heavy
    imb, _, _ = top_n_imbalance(_book([1.0] * 10, [1.0] * 10))
    assert imb == 0.0


def test_imbalance_uses_only_top_10_levels():
    # 15 levels per side; only the first 10 count under the locked N=10.
    imb, bid, ask = top_n_imbalance(_book([1.0] * 10 + [99.0] * 5,
                                          [2.0] * 10 + [0.1] * 5))
    assert bid == 10.0 and ask == 20.0
    assert imb == pytest.approx(-1 / 3)


def test_empty_book_refused():
    with pytest.raises(ValueError):
        top_n_imbalance(_book([], []))


def test_contemporaneity_guard():
    b = 1_000 * HOUR_MS
    assert boundary_ok(b, b)                     # exactly at the boundary
    assert boundary_ok(b + 45_000, b)            # the scheduled :00:45 case
    assert boundary_ok(b + MAX_LAG_MS, b)        # guard edge, inclusive
    assert not boundary_ok(b + MAX_LAG_MS + 1, b)  # one ms late -> skip
    assert not boundary_ok(b - 1, b)             # before the boundary -> skip
