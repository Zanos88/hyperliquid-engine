"""Hyperliquid public market-data feed (BTC-PERP OHLCV).

SCAFFOLD ONLY — endpoint confirmed in docs/RESEARCH_FINDINGS.md section
3.4: POST https://api.hyperliquid.xyz/info, body
{"type": "candleSnapshot", "req": {"coin", "interval", "startTime", "endTime"}}.
Implement so that callers never receive an in-progress (unclosed) candle —
this is a hard requirement (build spec section 11: no intra-candle
signal generation / no repainting).
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


def fetch_candles(
    coin: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: int,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[Candle]:
    """Fetch closed candles only.

    TODO(Fable): POST to HYPERLIQUID_INFO_URL with the candleSnapshot body,
    parse the response into Candle objects, and drop any candle whose
    close_time_ms is > end_time_ms (the API can return an in-progress
    trailing candle). See docs/RESEARCH_FINDINGS.md 3.4 for the exact
    request/response field names.
    """
    raise NotImplementedError


def fetch_meta(session: requests.Session | None = None, timeout: float = 10.0) -> dict:
    """Fetch perpetuals metadata (asset universe, szDecimals, maxLeverage).

    TODO(Fable): POST {"type": "meta"} to HYPERLIQUID_INFO_URL.
    """
    raise NotImplementedError


def get_btc_sz_decimals(session: requests.Session | None = None) -> int:
    """Live lookup of BTC's quantity-step precision (see RESEARCH_FINDINGS 3.4).

    TODO(Fable): find the "BTC" entry in fetch_meta()'s universe list and
    return its szDecimals (cited default is 5, but must be looked up live,
    not hardcoded — Hyperliquid can change per-asset metadata). Log a
    WARNING (never silently fall back) if the live lookup fails, per this
    project's no-silent-fallback rule.
    """
    raise NotImplementedError
