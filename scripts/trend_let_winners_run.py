"""Trend Engine — Let-Winners-Run Exits × Long-Only vs Both (driver).

BACKTEST ONLY, SIMULATED. Spot-capital accumulation framing, NOT comp/Propr.
Direct fix to the no-stop patient-hold study's flaw (first-profit inverts the
trend edge). Replaces the exit with the engine's OWN fib-extension target and
three other let-winners-run rules; the 4H bias-flip stays the catastrophe brake
under every model. Entries are the SAME 8 the +2.86R baseline produced
(reused via backtest.run_backtest on frozen snapshots — zero reimplementation).

5 exit models × 6 scenarios (long-only/short-only/both × single/concurrent,
cap 3) = 30 runs, all reported. Combinations are DEFERRED (multiple-comparisons
discipline on fixed n). Per-entry exit outcomes are scenario-independent, so we
simulate each entry once per model (40 sims) and the scenarios select/gate subsets.

Load-bearing caveat: the 8 entries are 7 SHORT + 1 LONG. Long-only scenarios are
n=1 (descriptive only, NOT a test); short-only (n=7) is where the real content
lives — both-directions is ~a short-side test already (7 of 8 trades).

Usage (from repo root):
    python scripts/trend_let_winners_run.py --selfcheck
    python scripts/trend_let_winners_run.py --phase run
Output: research/output/trend_let_winners_run.json + stdout tables.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_ROOT))

from factor_correlation_study import OUTPUT_DIR, load_snapshot  # noqa: E402
from backtest import NO_STOP_EXIT_MODELS, run_backtest, simulate_outcome  # noqa: E402
from strategy.bias_4h import compute_bias  # noqa: E402
from strategy.signals import DEFAULT_INDICATOR_CONFIG, Signal, SignalDirection  # noqa: E402
from strategy.timeframes import LOOKBACK_BARS  # noqa: E402

BARS_PER_DAY_1H = 24
CONCURRENT_CAP = 3          # flagged design choice, not tuned
MIN_MOVE_R = 1.0            # min-move arm threshold (flagged)
TRAIL_ARM_R = 1.0          # trailing arm threshold (flagged)
TRAIL_DIST_R = 1.0         # trailing distance (flagged; brief left it open)
FAVORABLE_EXITS = ("reversion", "fib_target", "resistance_rejection",
                   "min_move_profit", "trailing_stop")
OUT = OUTPUT_DIR / "trend_let_winners_run.json"
PRIOR_FIRST_PROFIT_NET_R = 5.70   # trend_no_stop.py both-directions ungated sum

BASELINE_DOC = {"trades": 8, "w_l": "4-4", "net_r": 2.86, "profit_factor": 1.43,
                "max_drawdown_r": 3.72}

SCENARIOS = [("long_single", "long", False), ("short_single", "short", False),
             ("both_single", "both", False),
             ("long_concurrent", "long", True), ("short_concurrent", "short", True),
             ("both_concurrent", "both", True)]


def _pctl(v, q):
    return round(v[min(len(v) - 1, math.ceil(q * len(v)) - 1)], 2) if v else None


def precompute_series(candles_4h):
    """Single compute_bias pass → (bias4h ms→Bias for the brake, sr4h ms→BiasResult
    for resistance-rejection), same trailing LOOKBACK_BARS slice as entries."""
    bias4h, sr4h = [], []
    for k in range(len(candles_4h)):
        br = compute_bias(candles_4h[max(0, k + 1 - LOOKBACK_BARS): k + 1])
        ms = candles_4h[k].close_time_ms
        bias4h.append((ms, br.bias))
        sr4h.append((ms, br))
    return bias4h, sr4h


def simulate_entry(st, entry_index, candles_1h, bias4h, sr4h, model):
    sig = Signal(direction=SignalDirection(st.direction), entry=st.entry, stop=st.stop,
                 target=st.target, reward_risk=st.reward_risk, timestamp=st.entry_ts,
                 bias_reason="reconstructed", trigger_reason="reconstructed")
    return simulate_outcome(candles_1h, entry_index, sig, patient_hold_exit=True,
                            bias4h_series=bias4h, exit_model=model,
                            sr4h_series=(sr4h if model == "resistance_rejection" else None),
                            min_move_r=MIN_MOVE_R, trail_arm_r=TRAIL_ARM_R,
                            trail_dist_r=TRAIL_DIST_R)


def gate(entries, concurrent, cap=CONCURRENT_CAP):
    """entries: dicts sorted by entry_index. Single = one position at a time;
    concurrent = admit while < cap open, else skip+log."""
    admitted, skipped_cap, skipped_single, util = [], 0, 0, 0
    for e in entries:
        open_now = [x for x in admitted if x["exit_index"] >= e["entry_index"]]
        if concurrent:
            if len(open_now) < cap:
                if open_now:
                    util += 1
                admitted.append(e)
            else:
                skipped_cap += 1
        else:
            if not open_now:
                admitted.append(e)
            else:
                skipped_single += 1
    return admitted, skipped_cap, skipped_single, util


def combined_exposure(admitted, candles_1h):
    """Worst-case simultaneous adverse across concurrently-open positions."""
    if not admitted:
        return {"max_concurrent": 0, "worst_combined_adverse_pct": 0.0,
                "worst_combined_adverse_r": 0.0}
    lo = min(a["entry_index"] for a in admitted)
    hi = max(a["exit_index"] for a in admitted)
    max_conc, worst_frac, worst_r = 0, 0.0, 0.0
    for t in range(lo + 1, hi + 1):
        opens = [a for a in admitted if a["entry_index"] < t <= a["exit_index"]]
        if not opens:
            continue
        max_conc = max(max_conc, len(opens))
        c = candles_1h[t]
        cf = sum((c.low - a["entry"]) / a["entry"] if a["is_long"]
                 else (a["entry"] - c.high) / a["entry"] for a in opens)
        cr = sum(((c.low - a["entry"]) if a["is_long"] else (a["entry"] - c.high)) / a["risk"]
                 for a in opens)
        worst_frac, worst_r = min(worst_frac, cf), min(worst_r, cr)
    return {"max_concurrent": max_conc,
            "worst_combined_adverse_pct": round(worst_frac * 100, 2),
            "worst_combined_adverse_r": round(worst_r, 2)}


def _trade_row(a):
    t = a["tr"]
    return {"entry_ts": t.entry_ts.isoformat(), "dir": t.direction,
            "exit_reason": t.exit_reason, "bars_held": t.bars_held,
            "days_held": round(t.bars_held / BARS_PER_DAY_1H, 2),
            "net_r": round(t.net_r, 3) if t.net_r is not None else None,
            "mae_pct": round(t.mae_frac * 100, 2) if t.mae_frac is not None else None,
            "mae_r": round(t.mae_r, 2) if t.mae_r is not None else None}


def summarize_cell(admitted, concurrent, candles_1h, gate_stats):
    trs = [a["tr"] for a in admitted]
    resolved = [t for t in trs if t.exit_reason != "unresolved"]
    nets = [t.net_r for t in resolved if t.net_r is not None]
    wins = [n for n in nets if n > 0]
    maes_frac = [t.mae_frac for t in trs if t.mae_frac is not None]
    maes_r = [t.mae_r for t in trs if t.mae_r is not None]
    ttr = sorted(t.bars_held / BARS_PER_DAY_1H for t in trs
                 if t.exit_reason in FAVORABLE_EXITS)
    total = sum(nets)
    by_val = sorted(nets, reverse=True)
    dom = {"total_net_r": round(total, 3),
           "top1_net_r": round(by_val[0], 3) if by_val else None,
           "net_ex_top1": round(total - by_val[0], 3) if by_val else None,
           "net_ex_top2": round(total - sum(by_val[:2]), 3) if len(by_val) >= 2 else None,
           "single_trade_flips_sign": (bool(by_val) and total > 0 >= (total - by_val[0]))}
    skipped_cap, skipped_single, util = gate_stats
    cell = {
        "n_admitted": len(trs), "resolved": len(resolved), "unresolved": len(trs) - len(resolved),
        "wins": len(wins), "win_rate": round(len(wins) / len(resolved), 3) if resolved else None,
        "net_r": round(total, 3), "avg_net_r": round(total / len(nets), 3) if nets else None,
        "worst_mae_pct": round(min(maes_frac) * 100, 2) if maes_frac else None,
        "worst_mae_r": round(min(maes_r), 2) if maes_r else None,
        "exit_reasons": {r: sum(1 for t in trs if t.exit_reason == r)
                         for r in FAVORABLE_EXITS + ("bias_flip", "unresolved")
                         if any(t.exit_reason == r for t in trs)},
        "time_to_exit_days": {"median": _pctl(ttr, 0.5), "p90": _pctl(ttr, 0.9),
                              "max": round(ttr[-1], 2) if ttr else None, "n": len(ttr)},
        "dominance": dom,
        "gate": {"skipped_by_cap": skipped_cap, "skipped_single_gate": skipped_single,
                 "concurrency_utilization": util},
        "small_sample_flag": (f"n={len(trs)} — descriptive only, not a test"
                              if len(trs) < 10 else None),
        "trades": [_trade_row(a) for a in admitted],
    }
    if concurrent:
        cell["combined_exposure"] = combined_exposure(admitted, candles_1h)
    return cell


def phase_run() -> None:
    candles_4h, _ = load_snapshot("4h")
    candles_1h, _ = load_snapshot("1h")
    w0 = datetime.fromtimestamp(candles_1h[0].close_time_ms / 1000, tz=timezone.utc)
    w1 = datetime.fromtimestamp(candles_1h[-1].close_time_ms / 1000, tz=timezone.utc)
    print(f"frozen snapshot: 1H {len(candles_1h)} bars, 4H {len(candles_4h)} bars "
          f"| window {w0:%Y-%m-%d} -> {w1:%Y-%m-%d}")

    # 1. Canonical entries from the stopped live config (cross-check +2.86R).
    stopped = run_backtest(candles_4h, candles_1h, dict(DEFAULT_INDICATOR_CONFIG),
                           stop_model="structural", target_model="fib_extension_preferred")
    stopped_trades = [t for t in stopped.pop("trades") if t.exit_reason != "unresolved"]
    n_long = sum(1 for t in stopped_trades if t.direction == "LONG")
    print(f"\nSTOPPED baseline on snapshot: {stopped['resolved']} trades "
          f"{stopped['wins']}-{stopped['losses']} | net {stopped['net_r']:+.2f}R "
          f"| PF {round(stopped['profit_factor'], 2)} | maxDD {stopped['max_drawdown_r']:.2f}R "
          f"(doc +2.86R) | dir split: {n_long} LONG / {len(stopped_trades) - n_long} SHORT")
    n_short = len(stopped_trades) - n_long
    if n_long <= 1:
        print(f"  ** long-only scenarios are n={n_long} (descriptive only, NOT a test); "
              f"short-only n={n_short} carries the content **")

    # 2. Per-entry outcome under each model (scenario-independent). 40 sims.
    bias4h, sr4h = precompute_series(candles_4h)
    idx_by_dt = {datetime.fromtimestamp(c.close_time_ms / 1000, tz=timezone.utc): i
                 for i, c in enumerate(candles_1h)}
    base = []
    for st in stopped_trades:
        i = idx_by_dt[st.entry_ts]
        base.append({"st": st, "entry_index": i, "is_long": st.direction == "LONG",
                     "entry": st.entry, "risk": abs(st.entry - st.stop)})

    per_entry = {m: [] for m in NO_STOP_EXIT_MODELS}
    for m in NO_STOP_EXIT_MODELS:
        for b in base:
            tr = simulate_entry(b["st"], b["entry_index"], candles_1h, bias4h, sr4h, m)
            per_entry[m].append({**b, "tr": tr, "exit_index": b["entry_index"] + tr.bars_held})

    # regression tie to the prior study: first_profit, all 8, ungated
    fp_sum = sum(e["tr"].net_r for e in per_entry["first_profit"]
                 if e["tr"].net_r is not None)
    print(f"first_profit all-8 ungated sum: {fp_sum:+.2f}R "
          f"(prior trend_no_stop.py: +{PRIOR_FIRST_PROFIT_NET_R}R) "
          f"{'OK' if abs(fp_sum - PRIOR_FIRST_PROFIT_NET_R) < 0.05 else 'MISMATCH'}")

    # 3. Three-way reconciliation (stopped vs first_profit vs model), per model.
    fp_by_dt = {e["tr"].entry_ts: e["tr"] for e in per_entry["first_profit"]}
    st_by_dt = {t.entry_ts: t for t in stopped_trades}
    three_way = {}
    for m in NO_STOP_EXIT_MODELS:
        rows = []
        for e in per_entry[m]:
            t, dt = e["tr"], e["tr"].entry_ts
            s, fp = st_by_dt[dt], fp_by_dt[dt]
            rows.append({"entry_ts": dt.isoformat(), "dir": t.direction,
                         "stopped_exit": s.exit_reason, "stopped_net_r": round(s.net_r, 3),
                         "first_profit_exit": fp.exit_reason,
                         "first_profit_net_r": round(fp.net_r, 3) if fp.net_r is not None else None,
                         "model_exit": t.exit_reason,
                         "model_net_r": round(t.net_r, 3) if t.net_r is not None else None,
                         "model_days": round(t.bars_held / BARS_PER_DAY_1H, 2),
                         "model_mae_pct": round(t.mae_frac * 100, 2) if t.mae_frac is not None else None,
                         "model_mae_r": round(t.mae_r, 2) if t.mae_r is not None else None})
        three_way[m] = rows

    # 4. The 20 cells.
    cells = {}
    print("\n=== 30-RUN MATRIX (model × scenario) ===")
    print(f"{'model':<24}{'scenario':<18}{'n':>3} {'net R':>8} {'wins':>5} "
          f"{'wMAE%':>7} {'wMAE R':>7} {'maxConc':>8} exits")
    for m in NO_STOP_EXIT_MODELS:
        for sc_name, direction, concurrent in SCENARIOS:
            pool = [e for e in per_entry[m]
                    if direction == "both" or e["is_long"] == (direction == "long")]
            pool = sorted(pool, key=lambda e: e["entry_index"])
            admitted, sk_cap, sk_single, util = gate(pool, concurrent)
            cell = summarize_cell(admitted, concurrent, candles_1h, (sk_cap, sk_single, util))
            cells[f"{m}|{sc_name}"] = cell
            mc = cell.get("combined_exposure", {}).get("max_concurrent", "-")
            print(f"{m:<24}{sc_name:<18}{cell['n_admitted']:>3} {cell['net_r']:>+8.2f} "
                  f"{cell['wins']:>5} {str(cell['worst_mae_pct']):>7} {str(cell['worst_mae_r']):>7} "
                  f"{str(mc):>8} {cell['exit_reasons']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "SIMULATED — frozen 4H/1H snapshot; live trend entries; let-winners-run "
                "no-stop exits; 4H bias-flip brake. NOT live/comp. Combinations deferred.",
        "window": {"from": w0.isoformat(), "to": w1.isoformat(),
                   "trigger_bars": len(candles_1h)},
        "config": "default indicators, 4h bias / 1h trigger, structural stop "
                  "(eligibility+sizing only), fib_extension_preferred target",
        "defaults": {"concurrent_cap": CONCURRENT_CAP, "min_move_r": MIN_MOVE_R,
                     "trail_arm_r": TRAIL_ARM_R, "trail_dist_r": TRAIL_DIST_R,
                     "note": "flagged design choices, not tuned"},
        "baseline_doc": BASELINE_DOC,
        "stopped_on_snapshot": {k: (round(v, 3) if isinstance(v, float) else v)
                                for k, v in stopped.items() if k != "trades"},
        "direction_split": {"long": n_long, "short": len(stopped_trades) - n_long},
        "first_profit_all8_ungated_net_r": round(fp_sum, 3),
        "prior_first_profit_net_r": PRIOR_FIRST_PROFIT_NET_R,
        "three_way_reconciliation": three_way,
        "cells": cells,
    }, indent=1), encoding="utf-8")
    print(f"\nwritten: {OUT}")


def phase_selfcheck() -> None:
    """Gate, combined-exposure, and dominance on hand-built entries."""
    from data.feed import Candle

    def C(i, o, h, l, c):
        return Candle(i * 3600000, (i + 1) * 3600000, o, h, l, c, 100.0)

    class T:  # minimal TradeResult stand-in
        def __init__(self, net_r, reason, bars, mae):
            self.net_r, self.exit_reason, self.bars_held = net_r, reason, bars
            self.mae_frac, self.mae_r = mae, mae * 20
            self.entry_ts, self.direction = datetime(2026, 1, 1, tzinfo=timezone.utc), "LONG"

    def E(entry_index, exit_index, is_long=True, entry=100.0, risk=5.0, net_r=1.0,
          reason="fib_target", mae=-0.05):
        return {"entry_index": entry_index, "exit_index": exit_index, "is_long": is_long,
                "entry": entry, "risk": risk, "tr": T(net_r, reason, exit_index - entry_index, mae)}

    # single gate: overlapping second entry is dropped
    pool = [E(0, 50), E(10, 60), E(70, 80)]
    adm, sc, ss, ut = gate(pool, concurrent=False)
    assert len(adm) == 2 and ss == 1, (len(adm), ss)   # [0..50] admits, [10..60] blocked, [70..80] admits
    # concurrent cap=3: 4th overlapping entry skipped
    pool2 = [E(0, 100), E(1, 100), E(2, 100), E(3, 100)]
    adm2, sc2, ss2, ut2 = gate(pool2, concurrent=True, cap=3)
    assert len(adm2) == 3 and sc2 == 1 and ut2 == 2, (len(adm2), sc2, ut2)
    # combined exposure: two positions underwater at once
    candles = [C(i, 100, 101, 90, 100) for i in range(6)]  # low 90 => -10% each
    exp = combined_exposure([E(0, 4), E(0, 4)], candles)
    assert exp["max_concurrent"] == 2
    assert exp["worst_combined_adverse_pct"] == -20.0     # two × -10%
    # dominance: one big winner carries a net that flips sign without it
    cell = summarize_cell([E(0, 1, net_r=5.0, reason="fib_target"),
                           E(2, 3, net_r=-1.0, reason="bias_flip", mae=-0.1)],
                          False, candles, (0, 0, 0))
    assert cell["dominance"]["single_trade_flips_sign"] is True
    print("selfcheck: all assertions passed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--phase", choices=("selfcheck", "run"), default="run")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck or args.phase == "selfcheck":
        phase_selfcheck()
    else:
        phase_run()


if __name__ == "__main__":
    main()
