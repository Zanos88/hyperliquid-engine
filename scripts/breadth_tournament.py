"""Round-4 breadth tournament: round-3's trend family, cross-asset portfolio.

RESEARCH ONLY. Round 3 found every classic trend variant beat buy-and-hold
risk-adjusted on BTC but none cleared a single-asset luck bar — a power
failure, not a falsification. Round 4 re-tests the SAME seven variants,
unchanged (no new rules, no tuning), as an equal-weight portfolio across
the seven liquid assets with deep gap-free Hyperliquid 1D history:

    BTC, ETH, SOL, DOGE, XRP, AVAX, LINK   (all >= 2,100 bars from 2020-08/09)

Breadth is the literature-standard way trend is validated: averaging
per-asset sleeves multiplies effective sample. Everything else is identical
to round 3: long/flat, 0.075%/side fees per sleeve, no lookahead, 70/30
chronological split on the common window, family-max circular-shift luck
bar (same offset applied to every sleeve, preserving cross-asset signal
structure), mechanical selection, one-shot write-once holdout confirm.

Usage (repo root):
    python scripts/breadth_tournament.py --phase selfcheck
    python scripts/breadth_tournament.py --phase fetch     # freeze 6 alt snapshots
    python scripts/breadth_tournament.py --phase explore
    python scripts/breadth_tournament.py --phase confirm   # ONE SHOT
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

from strategy_tournament import (  # noqa: E402  (chains to repo root on sys.path)
    FEE,
    STRATEGIES,
    WARMUP,
    calibration_bar,
    log_returns,
    metrics,
    net_strategy_returns,
)
from factor_correlation_study import DATA_DIR, OUTPUT_DIR  # noqa: E402
from data.feed import Candle, fetch_candles  # noqa: E402
from strategy.timeframes import interval_seconds  # noqa: E402

# ── PRE-REGISTERED PROTOCOL (round 4) ───────────────────────────────────
UNIVERSE = ("BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK")
TF = "1d"
BPY = 365.0
SPLIT_FRACTION = 0.70
MIN_TOTAL_TRADES = 70          # >= ~10 per sleeve on exploration
N_SHIFTS = 200
SHIFT_SEED = 20260709
CALIBRATION_PCTL = 0.95
MIN_BARS = 2000

SELECTION_CRITERIA = (
    "highest exploration portfolio Sharpe among the 7 variants, requiring "
    ">= 70 total exploration trades AND Sharpe > family-max shift-null 95th "
    "pct AND Sharpe > equal-weight buy-and-hold exploration Sharpe"
)
CONFIRM_CRITERIA = "net > 0 AND Sharpe >= 0.5 AND Sharpe >= 0.5 x exploration Sharpe"

EXPLORE_OUT = OUTPUT_DIR / "breadth_explore.json"
CONFIRM_OUT = OUTPUT_DIR / "breadth_confirm.json"


def snap_path(coin: str) -> Path:
    return DATA_DIR / f"{coin}_1d_snapshot.json"


def _ms_to_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def fetch_and_snapshot(coin: str) -> dict:
    step_ms = interval_seconds(TF) * 1000
    now_ms = int(time.time() * 1000)
    candles = fetch_candles(coin, TF, now_ms - 5100 * step_ms, now_ms)
    n = len(candles)
    if n < MIN_BARS:
        raise RuntimeError(f"{coin}: only {n} candles — below {MIN_BARS} floor")
    gaps = [j for j in range(1, n)
            if candles[j].open_time_ms != candles[j - 1].open_time_ms + step_ms]
    if gaps:
        raise RuntimeError(f"{coin}: {len(gaps)} gaps (first at index {gaps[0]})")
    doc = {
        "coin": coin, "interval": TF, "source": "hyperliquid candleSnapshot",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bar_count": n,
        "first_close_utc": _ms_to_utc(candles[0].close_time_ms),
        "last_close_utc": _ms_to_utc(candles[-1].close_time_ms),
        "schema": ["open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"],
        "candles": [[c.open_time_ms, c.close_time_ms, c.open, c.high, c.low, c.close, c.volume]
                    for c in candles],
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snap_path(coin).write_text(json.dumps(doc), encoding="utf-8")
    return doc


def load_asset(coin: str) -> list[Candle]:
    doc = json.loads(snap_path(coin).read_text(encoding="utf-8"))
    return [Candle(*row) for row in doc["candles"]]


# ── portfolio construction ──────────────────────────────────────────────

def build_universe() -> dict:
    """Load all sleeves, align on the common daily timeline (intersection of
    close times, restricted to bars past each sleeve's warm-up)."""
    assets = {coin: load_asset(coin) for coin in UNIVERSE}
    # Per-asset series keyed by close_time_ms.
    per_asset = {}
    for coin, candles in assets.items():
        rets = log_returns(candles)
        eligible = {candles[j].close_time_ms: j for j in range(WARMUP + 1, len(candles))}
        per_asset[coin] = {"candles": candles, "rets": rets, "eligible": eligible}
    common_ts = sorted(set.intersection(*(set(p["eligible"]) for p in per_asset.values())))
    if len(common_ts) < 1500:
        raise RuntimeError(f"common window only {len(common_ts)} bars")
    return {"per_asset": per_asset, "common_ts": common_ts}


def sleeve_series(universe: dict, positions_by_coin: dict[str, list[int]]) -> tuple[list[float], int]:
    """Equal-weight portfolio net return per common bar; also total trades
    across sleeves within the common window."""
    per_asset = universe["per_asset"]
    common_ts = universe["common_ts"]
    port = []
    total_trades = 0
    nets = {}
    for coin, p in per_asset.items():
        nets[coin] = net_strategy_returns(positions_by_coin[coin], p["rets"])
    for ts in common_ts:
        vals = []
        for coin, p in per_asset.items():
            j = p["eligible"][ts]
            vals.append(nets[coin][j])
        port.append(sum(vals) / len(vals))
    for coin, p in per_asset.items():
        idx = [p["eligible"][ts] for ts in common_ts]
        pos = positions_by_coin[coin]
        total_trades += sum(abs(pos[j] - pos[j - 1]) for j in idx)
    return port, total_trades


def port_metrics(port: list[float], a: int, b: int) -> dict:
    dummy_pos = [0] * len(port)  # trades tracked separately at sleeve level
    m = metrics(port, dummy_pos, a, b, BPY)
    m.pop("trades")
    m.pop("exposure")
    return m


def split_bounds(n_common: int) -> tuple[int, int]:
    ee = math.floor(SPLIT_FRACTION * n_common) - 1
    return ee, n_common - 1


def analyze() -> dict:
    universe = build_universe()
    common_ts = universe["common_ts"]
    ee, last = split_bounds(len(common_ts))

    # Positions per variant per sleeve (causal, full series).
    pos_all = {name: {coin: fn(universe["per_asset"][coin]["candles"])
                      for coin in UNIVERSE}
               for name, fn in STRATEGIES.items()}

    variants = {}
    ports = {}
    for name in STRATEGIES:
        port, trades = sleeve_series(universe, pos_all[name])
        ports[name] = port
        m = port_metrics(port, 0, ee)
        m["total_trades"] = _trades_in_window(universe, pos_all[name], 0, ee)
        variants[name] = {"explore": m}

    # Equal-weight buy-and-hold benchmark (one entry fee per sleeve).
    bh_pos = {coin: [1] * len(universe["per_asset"][coin]["candles"]) for coin in UNIVERSE}
    bh_port, _ = sleeve_series(universe, bh_pos)
    bh_port[0] -= FEE
    bh_explore = port_metrics(bh_port, 0, ee)

    maxima = _shift_calibration(universe, pos_all, ee)
    return {
        "universe": list(UNIVERSE), "tf": TF,
        "common_bars": len(common_ts),
        "explore_window": f"{_ms_to_utc(common_ts[0])} .. {_ms_to_utc(common_ts[ee])}",
        "holdout_window": f"{_ms_to_utc(common_ts[ee + 1])} .. {_ms_to_utc(common_ts[last])}",
        "explore_end": ee, "last": last,
        "buy_hold_explore": bh_explore,
        "calibration_bar_sharpe": calibration_bar(maxima),
        "calibration_median": maxima[len(maxima) // 2],
        "variants": variants,
    }


def _trades_in_window(universe: dict, positions_by_coin: dict, a: int, b: int) -> int:
    common_ts = universe["common_ts"]
    total = 0
    for coin, p in universe["per_asset"].items():
        idx = [p["eligible"][ts] for ts in common_ts[a:b + 1]]
        pos = positions_by_coin[coin]
        total += sum(abs(pos[j] - pos[j - 1]) for j in idx)
    return total


def _shift_calibration(universe: dict, pos_all: dict, ee: int) -> list[float]:
    """Family-max portfolio Sharpe under circular rotation: every sleeve of a
    variant rotated by the SAME offset within the exploration window."""
    common_ts = universe["common_ts"]
    n = ee + 1
    rng = random.Random(SHIFT_SEED)
    offsets = rng.sample(range(1, n), min(N_SHIFTS, n - 1))
    # Precompute per-variant per-sleeve exploration-window position vectors.
    expl_pos = {}
    for name, by_coin in pos_all.items():
        expl_pos[name] = {}
        for coin, p in universe["per_asset"].items():
            idx = [p["eligible"][ts] for ts in common_ts[:n]]
            expl_pos[name][coin] = ([by_coin[coin][j] for j in idx], idx)
    maxima = []
    for s in offsets:
        best = -math.inf
        for name, by_coin in pos_all.items():
            rotated = {}
            for coin in UNIVERSE:
                seg, idx = expl_pos[name][coin]
                rot = seg[s:] + seg[:s]
                full = list(by_coin[coin])
                for k, j in enumerate(idx):
                    full[j] = rot[k]
                rotated[coin] = full
            port, _ = sleeve_series(universe, rotated)
            best = max(best, port_metrics(port, 0, n - 1)["sharpe"])
        maxima.append(best)
    maxima.sort()
    return maxima


def mechanical_selection(panel: dict) -> dict | None:
    best = None
    bar = panel["calibration_bar_sharpe"]
    bh = panel["buy_hold_explore"]["sharpe"]
    for name, v in panel["variants"].items():
        e = v["explore"]
        if e["total_trades"] < MIN_TOTAL_TRADES:
            continue
        if e["sharpe"] <= bar or e["sharpe"] <= bh:
            continue
        if best is None or e["sharpe"] > best["explore_sharpe"]:
            best = {"strategy": name, "explore_sharpe": e["sharpe"],
                    "explore_net_log_return": e["net_log_return"],
                    "explore_total_trades": e["total_trades"],
                    "calibration_bar": bar, "buy_hold_sharpe": bh}
    return best


# ── phases ──────────────────────────────────────────────────────────────

def phase_fetch() -> None:
    for coin in UNIVERSE:
        if coin == "BTC" and snap_path("BTC").exists():
            print("BTC: reusing round-3 frozen snapshot")
            continue
        doc = fetch_and_snapshot(coin)
        print(f"{coin}: {doc['bar_count']} bars  {doc['first_close_utc']} .. {doc['last_close_utc']}")


def phase_explore() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if EXPLORE_OUT.exists():
        print(f"REFUSING: {EXPLORE_OUT} exists — exploration already ran.")
        sys.exit(1)
    panel = analyze()
    print(f"universe: {', '.join(panel['universe'])}   common bars: {panel['common_bars']}")
    print(f"explore {panel['explore_window']}")
    print(f"holdout (reserved) {panel['holdout_window']}")
    bh = panel["buy_hold_explore"]
    print(f"EW buy&hold: net x{bh['net_multiple']:.2f}  sharpe {bh['sharpe']:+.2f}  maxDD(log) {bh['max_dd_log']:.2f}")
    print(f"luck bar (family-max shift p95 sharpe): {panel['calibration_bar_sharpe']:.2f} "
          f"(median {panel['calibration_median']:.2f})")
    for name, v in panel["variants"].items():
        e = v["explore"]
        print(f"  {name:12s} net x{e['net_multiple']:6.2f}  ann {e['ann_return_pct']:+7.1f}%  "
              f"sharpe {e['sharpe']:+.2f}  maxDD {e['max_dd_log']:.2f}  trades {e['total_trades']:4d}")
    selection = mechanical_selection(panel)
    result = {"panel": panel, "selection_criteria": SELECTION_CRITERIA,
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
    name = sel["strategy"]
    universe = build_universe()
    common_ts = universe["common_ts"]
    ee, last = split_bounds(len(common_ts))
    pos = {coin: STRATEGIES[name](universe["per_asset"][coin]["candles"]) for coin in UNIVERSE}
    port, _ = sleeve_series(universe, pos)
    hold = port_metrics(port, ee + 1, last)
    hold["total_trades"] = _trades_in_window(universe, pos, ee + 1, last)
    bh_pos = {coin: [1] * len(universe["per_asset"][coin]["candles"]) for coin in UNIVERSE}
    bh_port, _ = sleeve_series(universe, bh_pos)
    bh_hold = port_metrics(bh_port, ee + 1, last)
    passed = (hold["net_log_return"] > 0 and hold["sharpe"] >= 0.5
              and hold["sharpe"] >= 0.5 * sel["explore_sharpe"])
    result = {
        "selection": sel,
        "holdout_window": f"{_ms_to_utc(common_ts[ee + 1])} .. {_ms_to_utc(common_ts[last])}",
        "holdout": hold, "buy_hold_holdout": bh_hold,
        "confirm_criteria": CONFIRM_CRITERIA, "passed": passed,
        "ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    CONFIRM_OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    print(f"\nVERDICT: {'PASS' if passed else 'FAIL'}  ({CONFIRM_CRITERIA})")
    print(f"written (write-once): {CONFIRM_OUT}")


def phase_selfcheck() -> None:
    # Portfolio of identical sleeves equals the single sleeve.
    fake = [Candle(i * 86400000, i * 86400000 + 86399999,
                   100 + i, 100 + i, 100 + i, 100 + i, 0.0) for i in range(300)]
    rets = log_returns(fake)
    pos = STRATEGIES["sma50"](fake)
    net = net_strategy_returns(pos, rets)
    per_asset = {c: {"candles": fake, "rets": rets,
                     "eligible": {fake[j].close_time_ms: j for j in range(WARMUP + 1, len(fake))}}
                 for c in ("A", "B")}
    common = sorted(set.intersection(*(set(p["eligible"]) for p in per_asset.values())))
    uni = {"per_asset": per_asset, "common_ts": common}
    port, trades = sleeve_series(uni, {"A": pos, "B": pos})
    j0 = per_asset["A"]["eligible"][common[0]]
    assert all(abs(port[k] - net[j0 + k]) < 1e-12 for k in range(len(common)))
    # Universe constant matches round-3 STRATEGIES (7 variants).
    assert len(STRATEGIES) == 7 and len(UNIVERSE) == 7
    assert not EXPLORE_OUT.exists() or True  # informational only
    print("selfcheck: all assertions passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", required=True,
                        choices=("selfcheck", "fetch", "explore", "confirm"))
    args = parser.parse_args()
    if args.phase == "selfcheck":
        phase_selfcheck()
    elif args.phase == "fetch":
        phase_fetch()
    elif args.phase == "explore":
        phase_explore()
    else:
        phase_confirm()


if __name__ == "__main__":
    main()
