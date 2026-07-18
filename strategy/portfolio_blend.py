"""
Portfolio Blend Strategy: TSMOM30 + Funding-Rate Mean Reversion.

Combines two low-correlation signals on 1D candles:
- TSMOM30: trailing 30-day momentum (trend-following)
- Funding MR: long when funding rate percentile ≤ 30 (crowded-short mean reversion)

Signal logic:
  1. Always allocate CORE to TSMOM30
  2. When funding percentile ≤ 30th (BEAR regime), ADD up to +1x Funding MR position
  3. Net: 1x during normal periods, up to 2x during crowded-short events

Reference: research/study/funding-mr-tsmom30-portfolio — Sharpe 1.03, AnnRet 49.38%, NetMult 4.48x
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── Path config ──
_BASE = Path(__file__).resolve().parent.parent
_OUTPUT = _BASE / "research" / "output"
_REGIME_LABELS = _OUTPUT / "regime_labels_btc.json"


def _load_funding_labels() -> dict[int, str]:
    """Load funding-component labels from regime_labels_btc.json.
    
    Returns {close_time_ms: "BULL"|"BEAR"|"NEUTRAL"|None}
    where BEAR = funding ≤ 30th percentile (cheap shorts / good to go long).
    """
    doc = json.loads(_REGIME_LABELS.read_text())
    labels: dict[int, str] = {}
    for r in doc["labels"]:
        ms = r["close_ms"]
        fv = r.get("funding")
        if fv is not None:
            labels[ms] = fv
    return labels


def portfolio_positions(
    candles: list[Any],
    tsmom_lookback: int = 30,
) -> list[float]:
    """Compute blended position sizes: TSMOM30 baseline + Funding MR boost.
    
    Returns float positions in [0.0, 2.0]:
    - 1.0 = TSMOM30 baseline (trend-following)
    - 2.0 = TSMOM30 + Funding MR boost (both signals active)
    - 0.0 = flat (neither signal active)
    
    To implement at 1x max leverage:
        cap position at 1.0 → allocate 0.5 TSMOM30 + 0.5 FundMR when both fire
    
    To implement at 2x max leverage (recommended):
        cap position at 2.0 → full 1.0 TSMOM30 + 1.0 FundMR when both fire
    """
    funding_labels = _load_funding_labels()
    n = len(candles)
    pos: list[float] = [0.0] * n

    for i, c in enumerate(candles):
        # Need at least 365 bars for funding percentile warmup
        if i < 365:
            twap_active = False
        else:
            fv = funding_labels.get(c.close_time_ms)
            twap_active = fv == "BEAR"

        # TSMOM30: need at least 30 bars
        mom_active = i >= tsmom_lookback and c.close > candles[i - tsmom_lookback].close

        # Blend
        if mom_active and twap_active:
            pos[i] = 2.0  # both signals
        elif mom_active:
            pos[i] = 1.0  # TSMOM30 only
        elif twap_active:
            # Funding MR alone (rare — usually TSMOM30 is also long in these periods)
            pos[i] = 1.0
        else:
            pos[i] = 0.0  # flat

    return pos


# ── Convenience: build variant descriptions ──
VARIANTS = {
    "tsmom30_only": {
        "desc": "TSMOM30 baseline (no funding overlay)",
        "fn": lambda c: _tsmom_only(c),
    },
    "funding_mr_only": {
        "desc": "Funding MR only (long when funding ≤ 30th pct)",
        "fn": lambda c: _funding_only(c),
    },
    "portfolio_1x": {
        "desc": "1x max: 0.5 TSMOM30 + 0.5 FundMR when both fire",
        "fn": lambda c: [min(p, 1.0) for p in portfolio_positions(c)],
    },
    "portfolio_2x": {
        "desc": "2x max: 1.0 TSMOM30 + 1.0 FundMR when both fire",
        "fn": lambda c: portfolio_positions(c),
    },
}


def _tsmom_only(candles: list[Any], lookback: int = 30) -> list[float]:
    """Pure TSMOM30 signal (legacy, for comparison)."""
    return [
        1.0 if i >= lookback and c.close > candles[i - lookback].close else 0.0
        for i, c in enumerate(candles)
    ]


def _funding_only(candles: list[Any]) -> list[float]:
    """Pure funding MR (legacy, for comparison)."""
    labels = _load_funding_labels()
    return [
        1.0 if i >= 365 and labels.get(c.close_time_ms) == "BEAR" else 0.0
        for i, c in enumerate(candles)
    ]
