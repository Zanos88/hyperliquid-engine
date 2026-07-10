"""Trend dry-run forward test — paper-only, BTC 1D long/flat.

Forward-tests the round-3/4 tournament survivors (docs/STRATEGY_TOURNAMENT.md
section 10, protocol in docs/TREND_FORWARD_TEST.md) with zero capital risk:

    tsmom30  (primary)  long while close > close 30 daily bars ago
    sma50    (shadow)   long while close > SMA(50)
    buy_hold (benchmark) always long

Paper equity $100,000 per track, taker fee 0.075% per side on every position
change, marking convention identical to the tournaments: the position decided
at the close of bar j earns bar j+1's log return; the fee lands on the flip
bar. Marks go to the `trend_forward_marks` table ONLY — this process never
writes portfolio_telemetry / trade_execution_ledger / engine_state /
strategy_settings / risk_params (the floor-guard trigger reads
portfolio_telemetry's latest row unfiltered; see db/schema.sql).

Tick-and-exit and idempotent: each run fetches the last 300 closed 1D bars,
recomputes the deterministic position series, and inserts one mark per track
per unprocessed bar (UNIQUE + ON CONFLICT DO NOTHING). Reruns and overlapping
schedulers are no-ops; downtime up to ~270 days self-heals on the next run.

Usage:
    railway run --service btc-signal-bot python forward_test.py --once
    python forward_test.py --report            # read-only summary
    python forward_test.py --loop              # resident mode (future service)

Telegram: flips post audibly to the live channel tagged [TREND-FWD paper];
inception is silent. --no-telegram (or missing env) disables sends.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from datetime import datetime, timezone

from alerts.telegram import TelegramClient, TelegramConfigError
from data.feed import fetch_candles
from db.store import TelemetryStore
from strategy.timeframes import interval_seconds
from strategy.trend_rules import sma_positions, tsmom_positions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("forward_test")

SYMBOL = "BTC"
TF = "1d"
LOOKBACK_BARS = 300
MIN_HISTORY = 60          # bars of history required before a bar may be marked
START_EQUITY = 100_000.0
FEE = 0.00075             # taker 0.075% per side, on |position change|
POLL_SECONDS = 300
TAG = "[TREND-FWD paper]"

STRATEGIES = {
    "tsmom30": lambda cs: tsmom_positions(cs, 30),
    "sma50": lambda cs: sma_positions(cs, 50),
    "buy_hold": lambda cs: [1] * len(cs),
}


def _ms_to_utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def last_mark(conn, strategy: str):
    return conn.execute(
        "SELECT bar_open_time_ms, equity FROM trend_forward_marks "
        "WHERE strategy = %s AND symbol = %s ORDER BY bar_open_time_ms DESC LIMIT 1",
        (strategy, SYMBOL),
    ).fetchone()


def insert_mark(conn, strategy: str, candle, position: int, net: float,
                equity: float, flipped: bool) -> bool:
    """Returns True only when the row was actually inserted (not a rerun)."""
    cur = conn.execute(
        "INSERT INTO trend_forward_marks "
        "(bar_open_time_ms, bar_close_utc, strategy, symbol, close, position,"
        " bar_log_return, equity, flipped) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (strategy, bar_open_time_ms) DO NOTHING",
        (candle.open_time_ms, _ms_to_utc(candle.close_time_ms), strategy, SYMBOL,
         candle.close, position, net, equity, flipped),
    )
    return cur.rowcount == 1


def tick(store: TelemetryStore, telegram: TelegramClient | None) -> bool:
    """Process any unmarked closed bars. Returns True when >=1 mark was
    written (used by --loop to rate-limit the silent report)."""
    now_ms = int(time.time() * 1000)
    span = LOOKBACK_BARS * interval_seconds(TF) * 1000
    candles = fetch_candles(SYMBOL, TF, now_ms - span, now_ms)
    if len(candles) < MIN_HISTORY + 1:
        raise RuntimeError(f"only {len(candles)} candles fetched")
    conn = store._connect()
    inception_lines: list[str] = []
    wrote = False

    for name, rule in STRATEGIES.items():
        pos = rule(candles)
        lm = last_mark(conn, name)

        if lm is None:
            # Inception: start holding pos[last] from here; entry fee if long.
            j = len(candles) - 1
            p = pos[j]
            net = -FEE * p
            equity = START_EQUITY * math.exp(net)
            if insert_mark(conn, name, candles[j], p, net, equity, flipped=p != 0):
                wrote = True
                state = "LONG" if p else "FLAT"
                inception_lines.append(f"{name}: {state} @ ${candles[j].close:,.0f}")
                logger.info("inception %s %s equity=%.2f", name, state, equity)
            continue

        last_open, equity = lm[0], float(lm[1])
        if last_open < candles[MIN_HISTORY].open_time_ms:
            logger.error("%s: gap exceeds candle retention (last mark %s) — "
                         "manual restart of the forward test required", name, last_open)
            continue
        for j in range(1, len(candles)):
            if candles[j].open_time_ms <= last_open:
                continue
            r = math.log(candles[j].close / candles[j - 1].close)
            delta = abs(pos[j] - pos[j - 1])
            net = pos[j - 1] * r - FEE * delta
            equity *= math.exp(net)
            flipped = delta != 0
            if insert_mark(conn, name, candles[j], pos[j - 1], net, equity, flipped):
                wrote = True
                if flipped and telegram is not None and name != "buy_hold":
                    pnl = (equity / START_EQUITY - 1) * 100
                    state = "LONG" if pos[j] else "FLAT"
                    telegram.send(
                        f"<b>{TAG} {name} FLIP → {state}</b> @ ${candles[j].close:,.0f}"
                        f" | paper equity ${equity:,.0f} ({pnl:+.1f}% since inception)",
                        silent=False,
                    )
                logger.info("mark %s bar=%s pos_into=%d net=%.5f equity=%.2f%s",
                            name, _ms_to_utc(candles[j].close_time_ms).date(),
                            pos[j - 1], net, equity, " FLIP" if flipped else "")

    if inception_lines and telegram is not None:
        telegram.send(
            f"<b>{TAG} forward test inception</b> — BTC 1D, $100k paper each, "
            f"fee 0.075%/side.\n" + "\n".join(inception_lines) +
            "\nProtocol: docs/TREND_FORWARD_TEST.md (review gate ≥180d & ≥10 flips).",
            silent=True,
        )
    return wrote


def report_text(conn, symbol: str = SYMBOL) -> str | None:
    """The --report table as plain text (also posted silently per tick).
    Pure function of DB state — two calls on identical data must return
    identical output (regression-tested after the 2026-07-10 report-position
    confusion, which was a code change between calls, not nondeterminism)."""
    rows = conn.execute(
        "SELECT strategy, count(*), min(bar_close_utc), max(bar_close_utc), "
        "sum(CASE WHEN flipped THEN 1 ELSE 0 END) "
        "FROM trend_forward_marks WHERE symbol = %s GROUP BY strategy ORDER BY strategy",
        (symbol,),
    ).fetchall()
    if not rows:
        return None
    lines = [f"{'strategy':10s} {'marks':>5s} {'flips':>5s} {'equity':>12s} {'net%':>8s} "
             f"{'pos':>4s}  window"]
    for strategy, n, first, last_ts, flips in rows:
        eq_row = conn.execute(
            "SELECT equity, position, flipped FROM trend_forward_marks "
            "WHERE strategy = %s AND symbol = %s ORDER BY bar_open_time_ms DESC LIMIT 1",
            (strategy, symbol),
        ).fetchone()
        equity, position, flipped = float(eq_row[0]), eq_row[1], eq_row[2]
        # Display the CURRENT position (held from the last close onward).
        # Normal marks store the position held INTO the bar, so a flip at
        # that close means current = 1 - position; the inception row (n == 1)
        # already stores the position held FROM inception.
        current = position if n == 1 else ((1 - position) if flipped else position)
        net = (equity / START_EQUITY - 1) * 100
        lines.append(f"{strategy:10s} {n:5d} {flips:5d} {equity:12,.2f} {net:+7.2f}% "
                     f"{('LONG' if current else 'FLAT'):>4s}  {first:%Y-%m-%d} .. {last_ts:%Y-%m-%d}")
    return "\n".join(lines)


def report(store: TelemetryStore) -> None:
    print(report_text(store._connect()) or "no marks yet — run --once first")


def send_report(store: TelemetryStore, telegram: TelegramClient | None) -> None:
    """Silent per-tick status post — flips remain the only audible messages."""
    if telegram is None:
        return
    text = report_text(store._connect())
    if text:
        telegram.send(f"<b>{TAG} report</b>\n<pre>{text}</pre>", silent=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="single tick and exit")
    mode.add_argument("--loop", action="store_true", help="resident mode (poll %ds)" % POLL_SECONDS)
    mode.add_argument("--report", action="store_true", help="read-only summary")
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args()

    store = TelemetryStore()
    if args.report:
        report(store)
        return
    store.apply_schema()

    telegram: TelegramClient | None = None
    if not args.no_telegram:
        try:
            telegram = TelegramClient()
        except TelegramConfigError:
            logger.warning("Telegram env not set — running silent")

    if args.once:
        tick(store, telegram)
        report(store)
        send_report(store, telegram)  # every scheduled tick (<=3/day) posts silently
        return
    logger.info("resident loop, poll %ds", POLL_SECONDS)
    while True:
        try:
            # Loop mode polls every 5 min; report only on ticks that wrote
            # marks so a resident deployment can't emit 288 posts/day.
            if tick(store, telegram):
                send_report(store, telegram)
        except Exception:
            logger.warning("tick failed; retrying next poll", exc_info=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
