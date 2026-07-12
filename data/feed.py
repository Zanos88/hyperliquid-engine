"""Hyperliquid public market-data feed (BTC-PERP OHLCV).

Endpoint verified in docs/RESEARCH_FINDINGS.md section 3.4:
POST https://api.hyperliquid.xyz/info (no auth). Rate limits are
IP-weighted and candleSnapshot carries extra weight per 60 candles
returned — callers should request only the lookback needed (~300 bars),
never the 5,000-candle max. Only closed candles are ever returned to
callers (see fetch_candles), per the build spec's no-repainting rule.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass(frozen=True)
class Candle:
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def _parse_candle(raw: dict) -> Candle:
    return Candle(
        open_time_ms=raw["t"],
        close_time_ms=raw["T"],
        open=float(raw["o"]),
        high=float(raw["h"]),
        low=float(raw["l"]),
        close=float(raw["c"]),
        volume=float(raw["v"]),
    )


def fetch_candles(
    coin: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: int,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[Candle]:
    """Fetch closed candles only, oldest first.

    The candleSnapshot endpoint includes the in-progress candle as the
    last element; any candle whose close_time_ms is beyond end_time_ms is
    dropped so callers never see an unclosed bar.
    """
    body = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval, "startTime": start_time_ms, "endTime": end_time_ms},
    }
    http = session or requests.Session()
    resp = http.post(HYPERLIQUID_INFO_URL, json=body, timeout=timeout)
    resp.raise_for_status()
    raw_candles = resp.json()

    candles = [_parse_candle(c) for c in raw_candles]
    candles = [c for c in candles if c.close_time_ms <= end_time_ms]
    candles.sort(key=lambda c: c.open_time_ms)
    return candles


def fetch_meta(session: requests.Session | None = None, timeout: float = 10.0) -> dict:
    """Fetch perpetuals metadata (asset universe, szDecimals, maxLeverage)."""
    http = session or requests.Session()
    resp = http.post(HYPERLIQUID_INFO_URL, json={"type": "meta"}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_btc_sz_decimals(session: requests.Session | None = None) -> int:
    """Live lookup of BTC's quantity-step precision (RESEARCH_FINDINGS 3.4).

    Must be queried at runtime, never hardcoded. Raises LookupError if
    BTC is missing from the universe — the caller decides whether to fall
    back to risk.sizing.DEFAULT_BTC_SZ_DECIMALS, and must log a WARNING
    if it does (no silent fallbacks).
    """
    meta = fetch_meta(session=session)
    for asset in meta.get("universe", []):
        if asset.get("name") == "BTC":
            return int(asset["szDecimals"])
    raise LookupError("BTC not found in Hyperliquid perpetuals meta universe")


def fetch_l2_book(
    coin: str,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> dict:
    """Live L2 order-book snapshot: {coin, time (ms), levels: [bids, asks]},
    20 levels/side, each {px, sz, n}. LIVE-ONLY — Hyperliquid exposes no
    free historical depth (ORDERBOOK_IMBALANCE_LAYER.md Part A), so a missed
    snapshot is permanently unrecoverable."""
    http = session or requests.Session()
    resp = http.post(HYPERLIQUID_INFO_URL, json={"type": "l2Book", "coin": coin},
                     timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_funding_history(
    coin: str,
    start_time_ms: int,
    end_time_ms: int,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[tuple[int, float]]:
    """Full hourly funding-rate history as (time_ms, rate) tuples, oldest first.

    The endpoint caps responses at 500 rows, so this is the repo's first
    paginated fetch: advance startTime past the last returned row until a
    short page or end_time_ms is reached. BTC history begins 2023-05-12
    (verified 2026-07-09, OI_LIQUIDATION_PHASE0_PHASE1.md §0.1).
    """
    http = session or requests.Session()
    out: list[tuple[int, float]] = []
    cursor = start_time_ms
    while cursor <= end_time_ms:
        body = {"type": "fundingHistory", "coin": coin,
                "startTime": cursor, "endTime": end_time_ms}
        resp = http.post(HYPERLIQUID_INFO_URL, json=body, timeout=timeout)
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        out.extend((int(r["time"]), float(r["fundingRate"])) for r in page)
        if len(page) < 500:
            break
        cursor = int(page[-1]["time"]) + 1
    out.sort(key=lambda t: t[0])
    return [t for t in out if t[0] <= end_time_ms]
