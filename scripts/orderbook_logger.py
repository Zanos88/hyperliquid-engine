"""Order-book snapshot logger — the zero-cost interim for the imbalance layer.

Logs one LIVE l2Book snapshot per 1H bar close into `orderbook_snapshots`
(new table only — never touches shared live state), so forward attribution
evidence accrues while the historical-data (0xArchive) decision is on hold.
Hourly boundaries cover every current track's bar closes (1H/4H/12H/1D).

CONTEMPORANEITY GUARD (hard, per the pre-registered brief): a snapshot is
written ONLY when fetched within 120 seconds of the hour boundary it is
stamped with. Later runs log "off-boundary — skipped" and exit 0 — a stale
book attributed to a boundary would silently corrupt the future test. The
book is live-only, so missed hours (laptop off) are PERMANENT gaps; the
eventual attribution claims only covered entries.

Usage:
    railway run --service btc-signal-bot python scripts/orderbook_logger.py --once
    railway run --service btc-signal-bot python scripts/orderbook_logger.py --report
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.feed import fetch_l2_book  # noqa: E402
from db.store import TelemetryStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("orderbook_logger")

COIN = "BTC"
HOUR_MS = 3_600_000
TOP_N = 10
MAX_LAG_MS = 120_000   # the contemporaneity guard


def top_n_imbalance(levels: list, n: int = TOP_N) -> tuple[float, float, float]:
    """(imbalance, bid_vol, ask_vol) over the top-n levels of [bids, asks]."""
    bid_vol = sum(float(x["sz"]) for x in levels[0][:n])
    ask_vol = sum(float(x["sz"]) for x in levels[1][:n])
    total = bid_vol + ask_vol
    if total == 0:
        raise ValueError("empty book — refusing to log a zero-volume snapshot")
    return (bid_vol - ask_vol) / total, bid_vol, ask_vol


def boundary_ok(now_ms: int, boundary_ms: int, max_lag_ms: int = MAX_LAG_MS) -> bool:
    """True only when `now` is within the guard window AFTER the boundary."""
    return 0 <= now_ms - boundary_ms <= max_lag_ms


def once(store: TelemetryStore) -> None:
    now_ms = int(time.time() * 1000)
    boundary = (now_ms // HOUR_MS) * HOUR_MS
    if not boundary_ok(now_ms, boundary):
        logger.info("off-boundary — skipped (%.0fs past %s; guard is %ds)",
                    (now_ms - boundary) / 1000,
                    datetime.fromtimestamp(boundary / 1000, tz=timezone.utc),
                    MAX_LAG_MS // 1000)
        return
    book = fetch_l2_book(COIN)
    fetched_ms = int(book.get("time") or now_ms)
    if not boundary_ok(fetched_ms, boundary):
        logger.info("book timestamp drifted past the guard — skipped")
        return
    imb, bid_vol, ask_vol = top_n_imbalance(book["levels"])
    conn = store._connect()
    cur = conn.execute(
        """INSERT INTO orderbook_snapshots
           (bar_close_ms, coin, imbalance_top10, bid_vol_top10, ask_vol_top10,
            best_bid, best_ask, levels)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (coin, bar_close_ms) DO NOTHING""",
        (boundary, COIN, imb, bid_vol, ask_vol,
         float(book["levels"][0][0]["px"]), float(book["levels"][1][0]["px"]),
         json.dumps(book["levels"])),
    )
    logger.info("boundary %s: imbalance %+0.3f (bid %.2f / ask %.2f BTC)%s",
                datetime.fromtimestamp(boundary / 1000, tz=timezone.utc),
                imb, bid_vol, ask_vol,
                "" if cur.rowcount == 1 else " [already logged — no-op]")


def report(store: TelemetryStore) -> None:
    conn = store._connect()
    row = conn.execute(
        """SELECT count(*), min(bar_close_ms), max(bar_close_ms),
                  avg(imbalance_top10), min(imbalance_top10), max(imbalance_top10),
                  sum(CASE WHEN abs(imbalance_top10) >= 0.15 THEN 1 ELSE 0 END)
           FROM orderbook_snapshots WHERE coin = %s""", (COIN,),
    ).fetchone()
    n, lo, hi, avg, imin, imax, extreme = row
    if not n:
        print("no snapshots yet")
        return
    span_h = (hi - lo) / HOUR_MS + 1
    print(f"snapshots: {n} | span {datetime.fromtimestamp(lo/1000, tz=timezone.utc):%Y-%m-%d %H:%M} "
          f".. {datetime.fromtimestamp(hi/1000, tz=timezone.utc):%Y-%m-%d %H:%M} UTC "
          f"| coverage {n / span_h:.0%} of {span_h:.0f} hourly boundaries")
    print(f"imbalance: avg {float(avg):+.3f} | range [{float(imin):+.3f}, {float(imax):+.3f}] "
          f"| |imb| >= 0.15 on {extreme}/{n} rows ({extreme / n:.0%})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--report", action="store_true")
    args = parser.parse_args()
    store = TelemetryStore()
    if args.once:
        store.apply_schema()
        once(store)
    else:
        report(store)


if __name__ == "__main__":
    main()
