"""Offline unit tests for data/feed.py — the Hyperliquid market-data layer.

Previously the feed's fetch/parse/filter logic had zero coverage (tests
only imported the `Candle` dataclass). These tests exercise the pure
request-building, parsing, closed-candle filtering and pagination logic
with a fake `requests.Session`, so nothing hits the network. They pin two
build-spec-critical properties:

- `fetch_candles` never returns an unclosed candle (no repainting), and
  always returns oldest-first regardless of source order;
- `fetch_funding_history` walks the 500-row pages correctly and stops.
"""
from __future__ import annotations

import pytest

from data.feed import (
    Candle,
    _parse_candle,
    fetch_candles,
    fetch_funding_history,
    get_btc_sz_decimals,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):  # feed relies on this; fake is always 2xx
        pass

    def json(self):
        return self._payload


class _FakeSession:
    """Returns queued payloads in order and records each request body."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.bodies: list[dict] = []

    def post(self, url, json=None, timeout=None):  # noqa: A002 - mirror requests API
        self.bodies.append(json)
        return _FakeResponse(self._payloads.pop(0))


def _raw(t, T, o=1, h=1, low=1, c=1, v=1):
    return {"t": t, "T": T, "o": str(o), "h": str(h), "l": str(low), "c": str(c), "v": str(v)}


def test_parse_candle_coerces_types():
    c = _parse_candle(_raw(1, 2, o=10, h=12, low=9, c=11, v=3.5))
    assert c == Candle(open_time_ms=1, close_time_ms=2, open=10.0, high=12.0,
                       low=9.0, close=11.0, volume=3.5)
    assert isinstance(c.open, float) and isinstance(c.open_time_ms, int)


def test_fetch_candles_drops_unclosed_and_sorts():
    # Source is out of order and includes an in-progress candle whose
    # close_time (600) is past the requested endTime (550).
    session = _FakeSession([[
        _raw(300, 400),   # closed, but listed first
        _raw(100, 200),   # closed, oldest
        _raw(500, 600),   # UNCLOSED — must be dropped
    ]])
    out = fetch_candles("BTC", "1h", 0, 550, session=session)
    assert [c.close_time_ms for c in out] == [200, 400]  # unclosed gone, sorted
    body = session.bodies[0]
    assert body["type"] == "candleSnapshot"
    assert body["req"] == {"coin": "BTC", "interval": "1h", "startTime": 0, "endTime": 550}


def test_fetch_candles_empty_response():
    session = _FakeSession([[]])
    assert fetch_candles("BTC", "1h", 0, 100, session=session) == []


def test_get_btc_sz_decimals_reads_universe():
    session = _FakeSession([{"universe": [{"name": "ETH", "szDecimals": 4},
                                          {"name": "BTC", "szDecimals": 5}]}])
    assert get_btc_sz_decimals(session=session) == 5


def test_get_btc_sz_decimals_missing_btc_raises():
    session = _FakeSession([{"universe": [{"name": "ETH", "szDecimals": 4}]}])
    with pytest.raises(LookupError):
        get_btc_sz_decimals(session=session)


def test_fetch_funding_history_paginates_full_then_short_page():
    # First page is a full 500 rows (triggers another fetch), second is
    # short (stops the loop). One row is past end_time_ms and is filtered.
    page1 = [{"time": t, "fundingRate": "0.0001"} for t in range(1000, 1500)]
    page2 = [{"time": 1500, "fundingRate": "0.0002"},
             {"time": 1501, "fundingRate": "0.0002"},
             {"time": 2001, "fundingRate": "0.0002"}]  # beyond end -> dropped
    session = _FakeSession([page1, page2])
    out = fetch_funding_history("BTC", 1000, 2000, session=session)

    assert len(out) == 502  # 500 + 2, the 2001 row filtered out
    assert out[0] == (1000, 0.0001) and out[-1] == (1501, 0.0002)
    assert len(session.bodies) == 2  # exactly one extra page fetched
    # cursor advances past the last row of page 1 (1499 + 1)
    assert session.bodies[1]["startTime"] == 1500


def test_fetch_funding_history_single_short_page_stops_immediately():
    session = _FakeSession([[{"time": 1000, "fundingRate": "0.0001"}]])
    out = fetch_funding_history("BTC", 1000, 2000, session=session)
    assert out == [(1000, 0.0001)]
    assert len(session.bodies) == 1  # no second request on a short page
