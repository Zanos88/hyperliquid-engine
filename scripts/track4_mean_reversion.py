"""Track 4 — unconstrained mean-reversion (Fisher-4H exhaustion + SMA bias).

BACKTEST ONLY. Spot-capital context, EXPLICITLY NOT CHALLENGE-RELEVANT:
no stop exists, so worst-case loss is unbounded by design — max adverse
excursion (MAE) is reported per trade with the same prominence as P&L.
Depends on the Fisher fix (9da31ee) — refuses to run if the buggy
coefficient is detected.

Grid (24 runs, sized up front per the brief; position size is a pure
scaling of the same trade list, so 5%/10% are REPORTING COLUMNS, not run
axes): bias TF {1d, 12h} x SMA window {30, 50} x entry threshold
{2.0, 3.0} x hold cap {none, 14d, 30d}.

Rules (pre-registered):
  Entry  LONG when 4H Fisher <= -thr AND bias close > SMA(window);
         SHORT mirrored (Fisher >= +thr AND close < SMA). One open trade
         at a time. Entry/exit at bar close, fee 0.075%/side.
  Exit   first of: (a) reversion - close beats entry by the round-trip
         fee cost (trade net-profitable, the literal "closed once profit
         hits"); (b) Fisher-reversal - Fisher crosses back through +/-1.5
         (single pre-registered level: corrected 4H Fisher exceeds 2.0 on
         only ~0.2% of bars, so a 2.0 exit would almost never fire);
         (c) time cap (holding-period ceiling, NOT a price stop). Both
         (a)/(b) flags logged when they coincide.
  Sizing fixed % of INITIAL capital per trade (non-compounding), so
         worst-case $ figures are linear and transparent.

Usage: python scripts/track4_mean_reversion.py --phase {selfcheck,run}
Output: research/output/track4_results.json + stdout tables (no DB —
P&L here is %-of-capital, not R; backtest_runs' R-schema doesn't apply).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import DATA_DIR, OUTPUT_DIR, load_snapshot  # noqa: E402
from data.feed import Candle  # noqa: E402
from strategy.trigger_1h import fisher_transform, sma  # noqa: E402

BIAS_TFS = ("1d", "12h")
SMA_WINDOWS = (30, 50)
ENTRY_THRESHOLDS = (2.0, 3.0)
HOLD_CAPS_DAYS = (None, 14, 30)
SIZES_PCT = (5.0, 10.0)          # reporting columns
FEE = 0.00075                    # 0.075%/side
REVERSAL_EXIT_LEVEL = 1.5
WARMUP_4H = 60
START_CAPITAL = 100_000.0
BARS_PER_DAY_4H = 6

OUT = OUTPUT_DIR / "track4_results.json"


def _ms_to_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def bias_direction_series(bias_candles: list[Candle], window: int) -> tuple[list[int], list[int]]:
    closes = [c.close for c in bias_candles]
    s = sma(closes, window)
    # sma() passes values through during warm-up — treat warm-up as no-bias.
    dirs = [0 if i < window - 1 else (1 if closes[i] > s[i] else (-1 if closes[i] < s[i] else 0))
            for i in range(len(closes))]
    return dirs, [c.close_time_ms for c in bias_candles]


def run_config(candles_4h, fisher, bias_dirs, bias_close_ms, thr, cap_days) -> list[dict]:
    cap_bars = cap_days * BARS_PER_DAY_4H if cap_days else None
    trades: list[dict] = []
    open_t: dict | None = None
    for i in range(WARMUP_4H, len(candles_4h)):
        c = candles_4h[i]
        if open_t is not None:
            side = open_t["side"]
            e = open_t["entry"]
            # track adverse excursion intra-hold (long: lows; short: highs)
            adverse = (c.low / e - 1) if side == "LONG" else (e / c.high - 1) * -1 * -1
            if side == "LONG":
                adverse = c.low / e - 1
            else:
                adverse = (e - c.high) / e
            open_t["mae"] = min(open_t["mae"], adverse)
            held = i - open_t["entry_i"]
            ret = (c.close / e - 1) if side == "LONG" else (e - c.close) / e
            net = ret - 2 * FEE
            rev_hit = net > 0
            fis_hit = (fisher[i] >= REVERSAL_EXIT_LEVEL) if side == "LONG" \
                else (fisher[i] <= -REVERSAL_EXIT_LEVEL)
            cap_hit = cap_bars is not None and held >= cap_bars
            if rev_hit or fis_hit or cap_hit:
                reason = ("both" if (rev_hit and fis_hit)
                          else "reversion" if rev_hit
                          else "fisher_reversal" if fis_hit
                          else "time_cap")
                open_t.update(exit_i=i, exit_ts=_ms_to_utc(c.close_time_ms),
                              exit_px=c.close, net_pct=net * 100,
                              bars_held=held, exit_reason=reason)
                trades.append(open_t)
                open_t = None
            continue
        # flat: check entry at this close
        f = fisher[i]
        bj = bisect_right(bias_close_ms, c.close_time_ms) - 1
        b = bias_dirs[bj] if bj >= 0 else 0
        side = None
        if f <= -thr and b == 1:
            side = "LONG"
        elif f >= thr and b == -1:
            side = "SHORT"
        if side:
            open_t = {"side": side, "entry_i": i, "entry": c.close,
                      "entry_ts": _ms_to_utc(c.close_time_ms),
                      "fisher_at_entry": round(f, 2), "mae": 0.0}
    if open_t is not None:
        c = candles_4h[-1]
        e = open_t["entry"]
        ret = (c.close / e - 1) if open_t["side"] == "LONG" else (e - c.close) / e
        open_t.update(exit_i=None, exit_ts="OPEN", exit_px=c.close,
                      net_pct=(ret - 2 * FEE) * 100,
                      bars_held=len(candles_4h) - 1 - open_t["entry_i"],
                      exit_reason="unresolved")
        trades.append(open_t)
    return trades


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0}
    nets = [t["net_pct"] for t in trades]
    maes = [t["mae"] * 100 for t in trades]
    reverted = [t for t in trades if t["exit_reason"] in ("reversion", "both")]
    holds = sorted(t["bars_held"] / BARS_PER_DAY_4H for t in reverted)
    def pct(sorted_vals, q):
        return sorted_vals[min(len(sorted_vals) - 1, math.ceil(q * len(sorted_vals)) - 1)]
    worst_i = min(range(len(trades)), key=lambda k: maes[k])
    return {
        "trades": len(trades),
        "wins": sum(1 for n in nets if n > 0),
        "sum_net_pct_position": round(sum(nets), 2),
        "capital_pnl_pct": {f"{s:.0f}%": round(sum(nets) * s / 100, 2) for s in SIZES_PCT},
        "exit_reasons": {r: sum(1 for t in trades if t["exit_reason"] == r)
                         for r in ("reversion", "fisher_reversal", "both", "time_cap", "unresolved")},
        "worst_mae_pct_position": round(min(maes), 2),
        "worst_mae_pct_capital": {f"{s:.0f}%": round(min(maes) * s / 100, 2) for s in SIZES_PCT},
        "worst_trade": {k: trades[worst_i][k] for k in
                        ("side", "entry_ts", "exit_ts", "exit_reason", "net_pct")} |
                       {"mae_pct_position": round(maes[worst_i], 2)},
        "time_to_revert_days": (None if not holds else
                                {"median": round(pct(holds, 0.5), 1),
                                 "p90": round(pct(holds, 0.9), 1),
                                 "max": round(holds[-1], 1), "n": len(holds)}),
    }


def phase_run() -> None:
    candles_4h, _ = load_snapshot("4h")
    fisher = fisher_transform(candles_4h)[0]
    # Guard: refuse to run on the buggy Fisher (saturated distribution).
    share_ge2 = sum(1 for v in fisher[20:] if abs(v) >= 2) / (len(fisher) - 20)
    if share_ge2 > 0.05:
        raise RuntimeError("Fisher distribution looks saturated — is the 9da31ee fix applied?")
    # Entry-condition frequency (the "why so few trades" table)
    freq = {f"|F| >= {t}": sum(1 for v in fisher[WARMUP_4H:] if abs(v) >= t)
            for t in ENTRY_THRESHOLDS}
    print(f"4H bars {len(candles_4h)} ({_ms_to_utc(candles_4h[0].close_time_ms)} .. "
          f"{_ms_to_utc(candles_4h[-1].close_time_ms)}); entry-condition bar counts: {freq}")

    bias = {}
    for tf in BIAS_TFS:
        bc, _ = load_snapshot(tf)
        for w in SMA_WINDOWS:
            bias[(tf, w)] = bias_direction_series(bc, w)

    results = []
    for tf in BIAS_TFS:
        for w in SMA_WINDOWS:
            dirs, times = bias[(tf, w)]
            for thr in ENTRY_THRESHOLDS:
                for cap in HOLD_CAPS_DAYS:
                    trades = run_config(candles_4h, fisher, dirs, times, thr, cap)
                    s = summarize(trades)
                    results.append({"bias_tf": tf, "sma": w, "thr": thr,
                                    "cap_days": cap, "summary": s, "trades": trades})
                    cap_s = f"{cap}d" if cap else "none"
                    if s["trades"]:
                        print(f"{tf}/SMA{w} thr={thr} cap={cap_s:>4}: trades {s['trades']} "
                              f"wins {s['wins']} | pos P&L {s['sum_net_pct_position']:+.2f}% "
                              f"| cap@10% {s['capital_pnl_pct']['10%']:+.2f}% "
                              f"| worstMAE(pos) {s['worst_mae_pct_position']:+.2f}% "
                              f"| exits {s['exit_reasons']}")
                    else:
                        print(f"{tf}/SMA{w} thr={thr} cap={cap_s:>4}: trades 0")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "entry_condition_bar_counts": freq, "grid_runs": len(results),
         "results": results}, indent=1), encoding="utf-8")
    print(f"\nwritten: {OUT} ({len(results)} configs)")


def phase_selfcheck() -> None:
    # Synthetic: price dips (Fisher forced negative), bias UP, then recovers.
    n = 120
    candles = []
    px = 100.0
    for i in range(n):
        px = 100 - 10 * math.sin(min(i, 40) / 40 * math.pi) if i < 40 else px * 1.01
        candles.append(Candle(i * 100, i * 100 + 99, px, px * 1.001, px * 0.999, px, 0.0))
    fisher = [-2.5 if 61 <= i <= 63 else 0.0 for i in range(n)]
    dirs = [1] * n
    times = [c.close_time_ms for c in candles]
    trades = run_config(candles, fisher, dirs, times, 2.0, None)
    # Fisher stays at -2.5 for 3 bars: enter @61, revert @62, re-enter @63 —
    # re-entry after a completed trade is by design (one at a time, not once).
    assert len(trades) == 2, trades
    for t in trades:
        assert t["side"] == "LONG" and t["exit_reason"] in ("reversion", "both")
        assert t["net_pct"] > 0
        assert t["mae"] <= 0  # adverse excursion is never positive
    # Time cap fires when nothing else does.
    fisher_flat = [-2.5 if i == 61 else 0.0 for i in range(n)]
    down = [Candle(i * 100, i * 100 + 99, 100 - i * 0.2, 100 - i * 0.2,
                   100 - i * 0.2 - 0.1, 100 - i * 0.2, 0.0) for i in range(n)]
    trades2 = run_config(down, fisher_flat, [1] * n, [c.close_time_ms for c in down], 2.0, 5)
    assert trades2 and trades2[0]["exit_reason"] == "time_cap"
    assert trades2[0]["net_pct"] < 0 and trades2[0]["mae"] < 0
    # Fisher-reversal exit can fire while unprofitable.
    fisher_rev = [-2.5 if i == 61 else (1.6 if i == 70 else 0.0) for i in range(n)]
    trades3 = run_config(down, fisher_rev, [1] * n, [c.close_time_ms for c in down], 2.0, None)
    assert trades3 and trades3[0]["exit_reason"] == "fisher_reversal" and trades3[0]["net_pct"] < 0
    print("selfcheck: all assertions passed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--phase", required=True, choices=("selfcheck", "run"))
    args = ap.parse_args()
    if args.phase == "selfcheck":
        phase_selfcheck()
    else:
        phase_run()


if __name__ == "__main__":
    main()
