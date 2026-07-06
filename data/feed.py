"""Hyperliquid public market-data feed (BTC-PERP OHLCV).

Endpoint confirmed in docs/RESEARCH_FINDINGS.md section 3.4:
POST https://api.hyperliquid.xyz/info, body {"type": "candleSnapshot", ...}.
Only closed candles are ever returned to callers (see `fetch_candles`),
per the build spec's "no intra-candle signal generation" requirement.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

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
    """Fetch closed candles only.

    The Hyperliquid candleSnapshot endpoint can include an in-progress
    candle as the last element; we drop any candle whose close_time_ms is
    in the future relative to end_time_ms to guarantee callers never see
    an unclosed bar.
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
    """Live lookup of BTC's quantity-step precision (see RESEARCH_FINDINGS 3.4).

    Falls back to the cited default of 5 only if the live lookup fails —
    the failure is the caller's responsibility to log, per the project's
    "no silent fallbacks" rule.
    """
    meta = fetch_meta(session=session)
    for asset in meta.get("universe", []):
        if asset.get("name") == "BTC":
            return int(asset["szDecimals"])
    raise LookupError("BTC not found in Hyperliquid perpetuals meta universe")
