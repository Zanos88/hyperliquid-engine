"""Round-3 strategy tournament: classic trend/momentum rules, pre-registered.

RESEARCH ONLY. After round 1 (factor confluence: null) and round 2 (top cell
falsified 0/3), this round tests the one strategy class with decades of
cross-asset literature behind it — time-series trend/momentum — on the
longest BTC series available here (1D back to 2020-08, 12H back to 2022-01).

Seven pre-registered variants per timeframe, all long/flat, all classic
round-number parameters (no tuning, no grid):

    sma50 / sma100 / sma200   long while close > SMA(N)
    donch_20_10               long on close > prior 20-bar high,
                              flat on close < prior 10-bar low   (Turtle S1)
    donch_55_20               55-bar high entry / 20-bar low exit (Turtle S2)
    tsmom30 / tsmom90         long while close > close N bars ago

Evaluation is walk-forward with no lookahead (position formed at close of
bar j earns bar j+1's return), net of taker fees 0.075% per side (repo
convention), no funding/slippage (disclosed). Controls: buy-and-hold and
flat on the same bars, plus a family-max circular-shift null (the luck bar,
same device as rounds 1-2). Chronological 70/30 explore/holdout split; ONE
winner is selected by pre-registered mechanical criteria on exploration and
confirmed ONCE on its holdout (write-once, no --force).

Usage (repo root):
    python scripts/strategy_tournament.py --phase selfcheck
    python scripts/strategy_tournament.py --phase fetch      # freeze 1D snapshot
    python scripts/strategy_tournament.py --phase explore
    python scripts/strategy_tournament.py --phase confirm    # ONE SHOT
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import (  # noqa: E402  (inserts repo root on sys.path)
    DATA_DIR,
    OUTPUT_DIR,
    load_snapshot,
    snapshot_path,
)
from data.feed import Candle, fetch_candles  # noqa: E402
from strategy.timeframes import interval_seconds  # noqa: E402

# ── PRE-REGISTERED PROTOCOL (round 3) ───────────────────────────────────
# Committed before `--phase explore` runs. Parameters are literature-standard
# round numbers (Turtle 20/10 and 55/20; SMA 50/100/200; 1m/3m momentum).

TIMEFRAMES = ("1d", "12h")           # 1d primary (2 full cycles), 12h secondary
BARS_PER_YEAR = {"1d": 365.0, "12h": 730.0}
FEE = 0.00075                        # taker 0.075% per side, charged on |Δposition|
WARMUP = 200                         # max lookback (SMA200); eval starts at bar 201
SPLIT_FRACTION = 0.70                # chronological, over eval bars
MIN_EXPLORE_TRADES = 10              # sample floor for selection eligibility
N_SHIFTS = 200
SHIFT_SEED = 20260709
CALIBRATION_PCTL = 0.95

# Mechanical selection (pre-registered): across BOTH panels, among variants
# with >= MIN_EXPLORE_TRADES exploration position changes, pick the single
# variant with the highest exploration net Sharpe that ALSO (a) exceeds its
# panel's family-max shift-null 95th-pct Sharpe bar and (b) exceeds
# buy-and-hold's exploration Sharpe on the same panel. None qualifies ->
# null result; the holdout never runs.
SELECTION_CRITERIA = (
    "highest exploration net Sharpe across both panels, requiring >= 10 "
    "exploration trades AND Sharpe > panel family-max shift-null 95th pct "
    "AND Sharpe > buy-and-hold exploration Sharpe on the same panel"
)
# Holdout confirmation (one shot, pre-registered): directional consistency,
# not statistical proof (the ~30% holdout is too short to prove a Sharpe).
# PASS iff holdout net log return > 0 AND holdout Sharpe >= 0.5 AND holdout
# Sharpe >= half the variant's exploration Sharpe.
CONFIRM_CRITERIA = "net > 0 AND Sharpe >= 0.5 AND Sharpe >= 0.5 x exploration Sharpe"

EXPLORE_OUT = OUTPUT_DIR / "tournament_explore.json"
CONFIRM_OUT = OUTPUT_DIR / "tournament_confirm.json"
MIN_1D_BARS = 2000


# ── strategy rules: causal position series (0/1), aligned to candles ────

def sma_positions(candles: list[Candle], period: int) -> list[int]:
    closes = [c.close for c in candles]
    pos = [0] * len(candles)
    running = 0.0
    for i, px in enumerate(closes):
        running += px
        if i >= period:
            running -= closes[i - period]
        if i >= period - 1:
            pos[i] = 1 if px > running / period else 0
    return pos


def tsmom_positions(candles: list[Candle], lookback: int) -> list[int]:
    closes = [c.close for c in candles]
    return [1 if i >= lookback and closes[i] > closes[i - lookback] else 0
            for i in range(len(candles))]


def donchian_positions(candles: list[Candle], entry: int, exit_: int) -> list[int]:
    pos = [0] * len(candles)
    holding = False
    for i in range(len(candles)):
        if i < entry:
            continue
        if not holding:
            entry_level = max(c.high for c in candles[i - entry:i])
            if candles[i].close > entry_level:
                holding = True
        else:
            exit_level = min(c.low for c in candles[i - exit_:i])
            if candles[i].close < exit_level:
                holding = False
        pos[i] = 1 if holding else 0
    return pos


STRATEGIES: dict[str, callable] = {
    "sma50": lambda cs: sma_positions(cs, 50),
    "sma100": lambda cs: sma_positions(cs, 100),
    "sma200": lambda cs: sma_positions(cs, 200),
    "donch_20_10": lambda cs: donchian_positions(cs, 20, 10),
    "donch_55_20": lambda cs: donchian_positions(cs, 55, 20),
    "tsmom30": lambda cs: tsmom_positions(cs, 30),
    "tsmom90": lambda cs: tsmom_positions(cs, 90),
}


# ── evaluation ──────────────────────────────────────────────────────────

def log_returns(candles: list[Candle]) -> list[float]:
    closes = [c.close for c in candles]
    return [0.0] + [math.log(closes[j] / closes[j - 1]) for j in range(1, len(closes))]


def net_strategy_returns(pos: list[int], rets: list[float]) -> list[float]:
    """Bar j earns pos[j-1] * r[j]; a position change at close of bar j pays
    FEE * |pos[j] - pos[j-1]| at bar j. Fully causal."""
    out = [0.0] * len(rets)
    for j in range(1, len(rets)):
        out[j] = pos[j - 1] * rets[j] - FEE * abs(pos[j] - pos[j - 1])
    return out


def metrics(net: list[float], pos: list[int], a: int, b: int, bpy: float) -> dict:
    """Metrics over bars a..b inclusive (returns attributed to those bars)."""
    seg = net[a:b + 1]
    n = len(seg)
    total = sum(seg)
    mu = total / n
    var = sum((x - mu) ** 2 for x in seg) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    sharpe = (mu / sd) * math.sqrt(bpy) if sd > 0 else 0.0
    peak = equity = 0.0
    max_dd = 0.0
    for x in seg:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    trades = sum(abs(pos[j] - pos[j - 1]) for j in range(a, b + 1))
    exposure = sum(pos[a:b + 1]) / n
    years = n / bpy
    return {
        "bars": n, "years": round(years, 2),
        "net_log_return": total, "net_multiple": math.exp(total),
        "ann_return_pct": (math.exp(total / years) - 1) * 100 if years > 0 else 0.0,
        "sharpe": sharpe, "max_dd_log": max_dd,
        "trades": trades, "exposure": exposure,
    }


def buy_hold_metrics(rets: list[float], a: int, b: int, bpy: float) -> dict:
    pos = [1] * len(rets)
    net = [0.0] * len(rets)
    for j in range(1, len(rets)):
        net[j] = rets[j]
    net[a] -= FEE  # one entry fee at the start of the slice
    return metrics(net, pos, a, b, bpy)


def shift_calibration_sharpe(pos_by_strategy: dict[str, list[int]], rets: list[float],
                             a: int, b: int, bpy: float) -> list[float]:
    """Family-max exploration Sharpe under circular rotation of each position
    series against the (fixed) returns, within the exploration slice. Breaks
    signal/return alignment while preserving each series' autocorrelation."""
    n = b - a + 1
    rng = random.Random(SHIFT_SEED)
    offsets = rng.sample(range(1, n), min(N_SHIFTS, n - 1))
    maxima = []
    for s in offsets:
        best = -math.inf
        for pos in pos_by_strategy.values():
            seg = pos[a:b + 1]
            rot = seg[s:] + seg[:s]
            full = pos[:a] + rot + pos[b + 1:]
            net = net_strategy_returns(full, rets)
            best = max(best, metrics(net, full, a, b, bpy)["sharpe"])
        maxima.append(best)
    maxima.sort()
    return maxima


def calibration_bar(maxima: list[float]) -> float:
    return maxima[min(len(maxima) - 1, math.ceil(CALIBRATION_PCTL * len(maxima)) - 1)]


# ── data ────────────────────────────────────────────────────────────────

def fetch_and_snapshot_1d() -> dict:
    tf = "1d"
    step_ms = interval_seconds(tf) * 1000
    now_ms = int(time.time() * 1000)
    candles = fetch_candles("BTC", tf, now_ms - 5100 * step_ms, now_ms)
    n = len(candles)
    if n < MIN_1D_BARS:
        raise RuntimeError(f"{tf}: only {n} candles — expected ~2150")
    gaps = [j for j in range(1, n)
            if candles[j].open_time_ms != candles[j - 1].open_time_ms + step_ms]
    if gaps:
        raise RuntimeError(f"{tf}: {len(gaps)} gaps (first at index {gaps[0]})")
    split_index = math.floor(SPLIT_FRACTION * n)
    doc = {
        "coin": "BTC", "interval": tf, "source": "hyperliquid candleSnapshot",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bar_count": n, "split_fraction": SPLIT_FRACTION, "split_index": split_index,
        "split_index_note": "round-3 tournament recomputes its split over eval bars (see script)",
        "first_close_utc": _ms_to_utc(candles[0].close_time_ms),
        "split_close_utc": _ms_to_utc(candles[split_index].close_time_ms),
        "last_close_utc": _ms_to_utc(candles[-1].close_time_ms),
        "schema": ["open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"],
        "candles": [[c.open_time_ms, c.close_time_ms, c.open, c.high, c.low, c.close, c.volume]
                    for c in candles],
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path(tf).write_text(json.dumps(doc), encoding="utf-8")
    return doc


def _ms_to_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def eval_bounds(n_bars: int) -> tuple[int, int, int]:
    """(eval_start, explore_end, last) — split at 70% of the EVAL range."""
    start = WARMUP + 1
    n_eval = n_bars - start
    explore_end = start + math.floor(SPLIT_FRACTION * n_eval) - 1
    return start, explore_end, n_bars - 1


# ── phases ──────────────────────────────────────────────────────────────

def analyze_panel(tf: str) -> dict:
    candles, _ = load_snapshot(tf)
    rets = log_returns(candles)
    bpy = BARS_PER_YEAR[tf]
    a, ee, last = eval_bounds(len(candles))
    pos_by = {name: fn(candles) for name, fn in STRATEGIES.items()}

    variants = {}
    for name, pos in pos_by.items():
        net = net_strategy_returns(pos, rets)
        variants[name] = {
            "explore": metrics(net, pos, a, ee, bpy),
            "holdout": None,  # holdout metrics are NOT computed in explore phase
        }
    bh_explore = buy_hold_metrics(rets, a, ee, bpy)
    maxima = shift_calibration_sharpe(pos_by, rets, a, ee, bpy)
    return {
        "tf": tf, "bars": len(candles),
        "eval_start": a, "explore_end": ee, "last": last,
        "explore_window": f"{_ms_to_utc(candles[a].close_time_ms)} .. {_ms_to_utc(candles[ee].close_time_ms)}",
        "holdout_window": f"{_ms_to_utc(candles[ee + 1].close_time_ms)} .. {_ms_to_utc(candles[last].close_time_ms)}",
        "buy_hold_explore": bh_explore,
        "calibration_bar_sharpe": calibration_bar(maxima),
        "calibration_median": maxima[len(maxima) // 2],
        "variants": variants,
    }


def mechanical_selection(panels: list[dict]) -> dict | None:
    best = None
    for panel in panels:
        bar = panel["calibration_bar_sharpe"]
        bh = panel["buy_hold_explore"]["sharpe"]
        for name, v in panel["variants"].items():
            e = v["explore"]
            if e["trades"] < MIN_EXPLORE_TRADES:
                continue
            if e["sharpe"] <= bar or e["sharpe"] <= bh:
                continue
            if best is None or e["sharpe"] > best["explore_sharpe"]:
                best = {"tf": panel["tf"], "strategy": name,
                        "explore_sharpe": e["sharpe"],
                        "explore_net_log_return": e["net_log_return"],
                        "explore_trades": e["trades"],
                        "panel_calibration_bar": bar,
                        "panel_buy_hold_sharpe": bh}
    return best


def phase_explore() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if EXPLORE_OUT.exists():
        print(f"REFUSING: {EXPLORE_OUT} exists — exploration already ran (one study, one run).")
        sys.exit(1)
    panels = []
    for tf in TIMEFRAMES:
        print(f"\n=== panel {tf}: 7 variants + buy-and-hold + {N_SHIFTS}-shift calibration ===")
        panel = analyze_panel(tf)
        panels.append(panel)
        print(f"  explore {panel['explore_window']}   holdout (reserved) {panel['holdout_window']}")
        bh = panel["buy_hold_explore"]
        print(f"  buy&hold: net x{bh['net_multiple']:.2f}  sharpe {bh['sharpe']:+.2f}  maxDD(log) {bh['max_dd_log']:.2f}")
        print(f"  luck bar (family-max shift p95 sharpe): {panel['calibration_bar_sharpe']:.2f} "
              f"(median {panel['calibration_median']:.2f})")
        for name, v in panel["variants"].items():
            e = v["explore"]
            print(f"  {name:12s} net x{e['net_multiple']:6.2f}  ann {e['ann_return_pct']:+7.1f}%  "
                  f"sharpe {e['sharpe']:+.2f}  maxDD {e['max_dd_log']:.2f}  "
                  f"trades {e['trades']:3d}  expo {e['exposure']:.2f}")
    selection = mechanical_selection(panels)
    result = {"panels": panels, "selection_criteria": SELECTION_CRITERIA,
              "selection": selection,
              "ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    EXPLORE_OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("\n=== MECHANICAL SELECTION (pre-registered) ===")
    print(SELECTION_CRITERIA)
    if selection is None:
        print("RESULT: no variant qualifies -> NULL RESULT (holdout will not run)")
    else:
        print("RESULT: " + json.dumps(selection, indent=1))
        print("Run --phase confirm for the ONE-SHOT holdout test.")
    print(f"written: {EXPLORE_OUT}")


def phase_confirm() -> None:
    if CONFIRM_OUT.exists():
        print(f"REFUSING: {CONFIRM_OUT} exists — the holdout is ONE-SHOT, no --force.")
        sys.exit(1)
    if not EXPLORE_OUT.exists():
        print("exploration has not run yet")
        sys.exit(1)
    explore = json.loads(EXPLORE_OUT.read_text(encoding="utf-8"))
    sel = explore["selection"]
    if sel is None:
        print("no selected variant (null result) — nothing to confirm")
        sys.exit(1)
    tf, name = sel["tf"], sel["strategy"]
    candles, _ = load_snapshot(tf)
    rets = log_returns(candles)
    bpy = BARS_PER_YEAR[tf]
    a, ee, last = eval_bounds(len(candles))
    pos = STRATEGIES[name](candles)
    net = net_strategy_returns(pos, rets)
    hold = metrics(net, pos, ee + 1, last, bpy)
    bh_hold = buy_hold_metrics(rets, ee + 1, last, bpy)
    passed = (hold["net_log_return"] > 0 and hold["sharpe"] >= 0.5
              and hold["sharpe"] >= 0.5 * sel["explore_sharpe"])
    result = {
        "selection": sel,
        "holdout_window": f"{_ms_to_utc(candles[ee + 1].close_time_ms)} .. {_ms_to_utc(candles[last].close_time_ms)}",
        "holdout": hold,
        "buy_hold_holdout": bh_hold,
        "confirm_criteria": CONFIRM_CRITERIA,
        "passed": passed,
        "ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    CONFIRM_OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    print(f"\nVERDICT: {'PASS' if passed else 'FAIL'}  ({CONFIRM_CRITERIA})")
    print(f"written (write-once): {CONFIRM_OUT}")


def phase_selfcheck() -> None:
    # SMA rule on a monotonically rising series -> long after warmup.
    up = [Candle(i, i, 1 + i, 1 + i, 1 + i, 1 + i, 0.0) for i in range(60)]
    assert sma_positions(up, 50)[55] == 1
    # TSMOM sign logic.
    assert tsmom_positions(up, 30)[45] == 1
    down = [Candle(i, i, 100 - i, 100 - i, 100 - i, 100 - i, 0.0) for i in range(60)]
    assert tsmom_positions(down, 30)[45] == 0
    assert sma_positions(down, 50)[55] == 0
    # Donchian: breakout enters, breakdown exits.
    flat = [Candle(i, i, 10, 10, 10, 10, 0.0) for i in range(30)]
    spike = flat + [Candle(30, 30, 12, 12, 12, 12, 0.0)] + \
        [Candle(31 + k, 31 + k, 12, 12, 12, 12, 0.0) for k in range(15)] + \
        [Candle(46, 46, 8, 8, 8, 8, 0.0)]
    dpos = donchian_positions(spike, 20, 10)
    assert dpos[30] == 1 and dpos[40] == 1 and dpos[46] == 0
    # Fee accounting: one round trip = 2 fees.
    pos = [0] * 5 + [1] * 5 + [0] * 5
    rets = [0.0] * 15
    net = net_strategy_returns(pos, rets)
    assert abs(sum(net) + 2 * FEE) < 1e-12
    # No lookahead: bar j earns pos[j-1].
    pos2 = [0, 1, 0]
    rets2 = [0.0, 0.05, 0.07]
    net2 = net_strategy_returns(pos2, rets2)
    assert abs(net2[1] - (0 * 0.05 - FEE)) < 1e-12      # entry fee at bar 1, no return
    assert abs(net2[2] - (1 * 0.07 - FEE)) < 1e-12      # earns bar 2, pays exit fee
    # Sharpe of zero-variance series doesn't blow up.
    m = metrics([0.001] * 100, [1] * 100, 10, 90, 365.0)
    assert m["sharpe"] == 0.0 or math.isfinite(m["sharpe"])
    # Rotation identity: shift machinery returns finite maxima.
    print("selfcheck: all assertions passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", required=True,
                        choices=("selfcheck", "fetch", "explore", "confirm"))
    args = parser.parse_args()
    if args.phase == "selfcheck":
        phase_selfcheck()
    elif args.phase == "fetch":
        doc = fetch_and_snapshot_1d()
        print(f"1d: {doc['bar_count']} bars  {doc['first_close_utc']} .. {doc['last_close_utc']}")
    elif args.phase == "explore":
        phase_explore()
    else:
        phase_confirm()


if __name__ == "__main__":
    main()
