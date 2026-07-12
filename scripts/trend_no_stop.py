"""Trend Engine — No-Stop Patient-Hold Accumulation Variant (driver).

BACKTEST ONLY, SIMULATED. Spot-capital accumulation framing, EXPLICITLY NOT
the Propr/comp account (same framing as Track 4). Tests the LIVE trend
engine's real, validated entries (4H bias + 1H Fisher/OBV confluence, R:R>=2
gate, structural stop) held patiently instead of stopped-and-targeted.

Method (reproducible, frozen snapshots — no live fetch, no DB):
  1. Run the live config's STOPPED baseline on the frozen 4H/1H snapshot
     (structural stop + fib_extension target) via backtest.run_backtest. This
     cross-checks docs/CORRECTED_BASELINE_4H1H.md (+2.86R, 8 trades) and gives
     the canonical entry set.
  2. Re-simulate EACH of those exact entries under the patient-hold exit
     (no stop ever placed; exit = first net-profitable close OR 4H bias flip
     off the trade's direction). Entries are held FIXED — the reconciliation's
     whole point is "same entries, different exit." Overlap is allowed, which
     is consistent with the spot-ACCUMULATION framing (not a one-position comp
     account), and is required because a patient hold blocks far longer than a
     stopped trade, so a gated re-run would silently change the entry set.

The stop is NEVER an exit here; it survives only as (a) the R:R>=2 entry gate
(applied inside evaluate_signal, unchanged) and (b) the sizing unit — P&L and
MAE are expressed in R against that never-placed stop (risk=|entry-stop|).

Per the brief: this is a NEW standalone test — its numbers are NOT the +2.86R
result plus Track 4's drawdown profile, and must not be blended with either.
Reported MAE-first (worst adverse excursion in % AND R), same standard as
Track 4's Aug-27 hostage trade.

Usage (from repo root):
    python scripts/trend_no_stop.py --phase selfcheck
    python scripts/trend_no_stop.py --phase run
Output: research/output/trend_no_stop.json + stdout tables.
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
from backtest import TradeResult, run_backtest, simulate_outcome  # noqa: E402
from strategy.bias_4h import Bias, compute_bias  # noqa: E402
from strategy.signals import DEFAULT_INDICATOR_CONFIG, Signal, SignalDirection  # noqa: E402
from strategy.timeframes import LOOKBACK_BARS  # noqa: E402

BARS_PER_DAY_1H = 24
OUT = OUTPUT_DIR / "trend_no_stop.json"

# The corrected live-config baseline this variant is reconciled against
# (docs/CORRECTED_BASELINE_4H1H.md, computed on corrected Fisher 9da31ee).
BASELINE_DOC = {"trades": 8, "w_l": "4-4", "net_r": 2.86, "profit_factor": 1.43,
                "max_drawdown_r": 3.72, "window": "2025-12-13 -> 2026-07-10 (~209d)"}


def _pctl(sorted_vals: list[float], q: float):
    if not sorted_vals:
        return None
    return sorted_vals[min(len(sorted_vals) - 1, math.ceil(q * len(sorted_vals)) - 1)]


def _precompute_bias4h(candles_4h) -> list[tuple[int, Bias]]:
    """Causal 4H-bias step function keyed by 4H close — SAME trailing
    LOOKBACK_BARS slice + compute_bias evaluate_signal uses for entries."""
    return [(candles_4h[k].close_time_ms,
             compute_bias(candles_4h[max(0, k + 1 - LOOKBACK_BARS): k + 1]).bias)
            for k in range(len(candles_4h))]


def patient_hold_on_entries(stopped_trades: list[TradeResult], candles_1h,
                            bias4h_series: list[tuple[int, Bias]]) -> list[TradeResult]:
    """Re-simulate each stopped-run entry under the patient-hold exit, holding
    the entry (direction/price/stop/target) FIXED. Reconstructs the entry
    Signal from the stopped TradeResult and locates its bar by close time."""
    idx_by_dt = {datetime.fromtimestamp(c.close_time_ms / 1000, tz=timezone.utc): i
                 for i, c in enumerate(candles_1h)}
    out: list[TradeResult] = []
    for st in stopped_trades:
        i = idx_by_dt[st.entry_ts]
        sig = Signal(direction=SignalDirection(st.direction), entry=st.entry, stop=st.stop,
                     target=st.target, reward_risk=st.reward_risk, timestamp=st.entry_ts,
                     bias_reason="reconstructed", trigger_reason="reconstructed")
        out.append(simulate_outcome(candles_1h, i, sig, patient_hold_exit=True,
                                    bias4h_series=bias4h_series))
    return out


def summarize_patient(trades: list[TradeResult]) -> dict:
    """MAE-first summary (P&L and worst adverse excursion equal prominence)."""
    if not trades:
        return {"trades": 0}
    resolved = [t for t in trades if t.exit_reason != "unresolved"]
    nets = [t.net_r for t in resolved if t.net_r is not None]
    wins = [n for n in nets if n > 0]
    maes_frac = [t.mae_frac for t in trades if t.mae_frac is not None]
    maes_r = [t.mae_r for t in trades if t.mae_r is not None]
    ttr_days = sorted(t.bars_held / BARS_PER_DAY_1H for t in trades
                      if t.exit_reason == "reversion")
    # descriptive cumulative-R in entry order (overlap allowed → flagged in doc)
    eq = peak = maxdd = 0.0
    for n in nets:
        eq += n
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    hostage = min(trades, key=lambda t: t.mae_frac if t.mae_frac is not None else 0.0)
    return {
        "trades": len(trades),
        "resolved": len(resolved),
        "unresolved": len(trades) - len(resolved),
        "wins": len(wins),
        "win_rate": (len(wins) / len(resolved)) if resolved else None,
        "net_r": round(sum(nets), 3),
        "avg_net_r": round(sum(nets) / len(nets), 3) if nets else None,
        "cumR_maxdd_entry_order": round(maxdd, 3),
        "worst_mae_pct": round(min(maes_frac) * 100, 2) if maes_frac else None,
        "worst_mae_r": round(min(maes_r), 2) if maes_r else None,
        "exit_reasons": {r: sum(1 for t in trades if t.exit_reason == r)
                         for r in ("reversion", "bias_flip", "unresolved")},
        "time_to_first_profit_days": ({"median": round(_pctl(ttr_days, 0.5), 2),
                                       "p90": round(_pctl(ttr_days, 0.9), 2),
                                       "max": round(ttr_days[-1], 2), "n": len(ttr_days)}
                                      if ttr_days else None),
        "hostage": {"entry_ts": hostage.entry_ts.isoformat(), "dir": hostage.direction,
                    "exit_reason": hostage.exit_reason,
                    "mae_pct": round(hostage.mae_frac * 100, 2),
                    "mae_r": round(hostage.mae_r, 2), "bars_held": hostage.bars_held,
                    "days_held": round(hostage.bars_held / BARS_PER_DAY_1H, 1)},
    }


def reconcile(stopped: list[TradeResult], patient: list[TradeResult]) -> list[dict]:
    """One row per (shared) entry: stopped vs patient outcome + verdict.
    Directly answers 'was the stop costing us or protecting us' per trade."""
    pat_by_dt = {t.entry_ts: t for t in patient}
    rows: list[dict] = []
    for s in stopped:
        p = pat_by_dt[s.entry_ts]
        delta = (p.net_r - s.net_r) if (p.net_r is not None and s.net_r is not None) else None
        if p.exit_reason == "unresolved":
            verdict = "open"
        elif delta is None:
            verdict = "n/a"
        elif abs(delta) < 0.05:
            verdict = "match"
        else:
            verdict = "help" if delta > 0 else "hurt"
        rows.append({
            "entry_ts": s.entry_ts.isoformat(), "dir": s.direction,
            "entry": round(s.entry, 1),
            "stopped_exit": s.exit_reason, "stopped_bars": s.bars_held,
            "stopped_net_r": round(s.net_r, 3) if s.net_r is not None else None,
            "patient_exit": p.exit_reason, "patient_bars": p.bars_held,
            "patient_days": round(p.bars_held / BARS_PER_DAY_1H, 1),
            "patient_net_r": round(p.net_r, 3) if p.net_r is not None else None,
            "patient_mae_pct": round(p.mae_frac * 100, 2) if p.mae_frac is not None else None,
            "patient_mae_r": round(p.mae_r, 2) if p.mae_r is not None else None,
            "delta_r": round(delta, 3) if delta is not None else None,
            "verdict": verdict,
        })
    return rows


def phase_run() -> None:
    candles_4h, _ = load_snapshot("4h")
    candles_1h, _ = load_snapshot("1h")
    w0 = datetime.fromtimestamp(candles_1h[0].close_time_ms / 1000, tz=timezone.utc)
    w1 = datetime.fromtimestamp(candles_1h[-1].close_time_ms / 1000, tz=timezone.utc)
    print(f"frozen snapshot: 1H trigger {len(candles_1h)} bars, 4H bias {len(candles_4h)} bars "
          f"| window {w0:%Y-%m-%d} -> {w1:%Y-%m-%d}")

    config = dict(DEFAULT_INDICATOR_CONFIG)
    # 1. STOPPED baseline (the live config) — canonical entries + cross-check.
    stopped_summary = run_backtest(candles_4h, candles_1h, config,
                                   stop_model="structural",
                                   target_model="fib_extension_preferred")
    stopped_trades = [t for t in stopped_summary.pop("trades")
                      if t.exit_reason != "unresolved"]  # resolved entries only
    print("\n=== STOPPED baseline on snapshot (cross-check vs +2.86R doc) ===")
    print(f"trades {stopped_summary['resolved']} | W-L {stopped_summary['wins']}-"
          f"{stopped_summary['losses']} | net {stopped_summary['net_r']:+.2f}R | "
          f"PF {stopped_summary['profit_factor'] and round(stopped_summary['profit_factor'], 2)} "
          f"| maxDD {stopped_summary['max_drawdown_r']:.2f}R | "
          f"supp_rr {stopped_summary['suppressed_rr']}")
    print(f"doc baseline: {BASELINE_DOC['trades']} | {BASELINE_DOC['w_l']} | "
          f"+{BASELINE_DOC['net_r']}R | PF {BASELINE_DOC['profit_factor']} | "
          f"maxDD {BASELINE_DOC['max_drawdown_r']}R ({BASELINE_DOC['window']})")

    # 2. PATIENT-HOLD on the exact same entries (held fixed, overlap allowed).
    bias4h_series = _precompute_bias4h(candles_4h)
    patient_trades = patient_hold_on_entries(stopped_trades, candles_1h, bias4h_series)
    psum = summarize_patient(patient_trades)
    rows = reconcile(stopped_trades, patient_trades)

    print("\n=== PATIENT-HOLD variant (no stop; first-profit OR 4H bias-flip) ===")
    print(f"trades {psum['trades']} | resolved {psum['resolved']} "
          f"(unresolved {psum['unresolved']}) | wins {psum['wins']} | "
          f"net {psum['net_r']:+.2f}R | avg {psum['avg_net_r']}R | "
          f"exits {psum['exit_reasons']}")
    print(f"worst MAE: {psum['worst_mae_pct']}%  ({psum['worst_mae_r']}R)  "
          f"| time-to-first-profit (d) {psum['time_to_first_profit_days']}")
    h = psum["hostage"]
    print(f"deepest hostage: {h['entry_ts'][:16]} {h['dir']} {h['exit_reason']} "
          f"MAE {h['mae_pct']}% ({h['mae_r']}R) held {h['days_held']}d")

    print("\n=== TRADE-BY-TRADE RECONCILIATION (same entries) ===")
    print(f"{'entry':<16} {'dir':<5} {'stopped':>18} {'patient':>28} {'delta':>7} verdict")
    for r in rows:
        st = f"{r['stopped_exit']} {r['stopped_net_r']:+.2f}R"
        pt = (f"{r['patient_exit']} {r['patient_net_r']:+.2f}R "
              f"MAE{r['patient_mae_pct']}%" if r['patient_net_r'] is not None
              else f"{r['patient_exit']} MAE{r['patient_mae_pct']}%")
        d = f"{r['delta_r']:+.2f}" if r['delta_r'] is not None else "  -"
        print(f"{r['entry_ts'][:16]:<16} {r['dir']:<5} {st:>18} {pt:>28} {d:>7} {r['verdict']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "SIMULATED — frozen 4H/1H snapshot; live trend config entries; "
                "no-stop patient-hold exit. NOT live performance; NOT comp/Propr.",
        "window": {"from": w0.isoformat(), "to": w1.isoformat(),
                   "trigger_bars": len(candles_1h), "bias_bars": len(candles_4h)},
        "config": "default indicators, 4h bias / 1h trigger, structural stop "
                  "(eligibility+sizing only), fib_extension_preferred target",
        "baseline_doc": BASELINE_DOC,
        "stopped_on_snapshot": {k: (round(v, 3) if isinstance(v, float) else v)
                                for k, v in stopped_summary.items() if k != "trades"},
        "patient_summary": psum,
        "reconciliation": rows,
    }, indent=1), encoding="utf-8")
    print(f"\nwritten: {OUT}")


def phase_selfcheck() -> None:
    """Exercise summarize_patient + reconcile on hand-built TradeResults
    (no evaluate_signal needed)."""
    def tr(ts_h, direction, net_r, reason, bars, mae_frac):
        ts = datetime.fromtimestamp(ts_h * 3600, tz=timezone.utc)
        mae_r = mae_frac * 100 / 5 if mae_frac is not None else None
        return TradeResult(entry_ts=ts, exit_ts=None, direction=direction, entry=100.0,
                           stop=95.0, target=110.0, reward_risk=2.0, exit_reason=reason,
                           gross_r=net_r, net_r=net_r, bars_held=bars, indicators_snapshot={},
                           mae_frac=mae_frac, mae_r=mae_r)

    # stopped: one loser (stopped -1.0R), one winner (target +2.0R)
    s1 = tr(10, "LONG", -1.0, "stop", 1, -0.05)
    s2 = tr(20, "SHORT", 2.0, "target", 3, -0.02)
    # patient on same entries: loser recovers to +0.3 (stop was COSTING -> help),
    #                          winner lags to +0.1 (target was better -> hurt)
    p1 = tr(10, "LONG", 0.3, "reversion", 40, -0.12)
    p2 = tr(20, "SHORT", 0.1, "reversion", 60, -0.02)
    rows = reconcile([s1, s2], [p1, p2])
    assert rows[0]["verdict"] == "help" and rows[0]["delta_r"] == 1.3, rows[0]
    assert rows[1]["verdict"] == "hurt" and rows[1]["delta_r"] == -1.9, rows[1]

    # a patient hostage still open at data end -> "open", MAE still surfaced
    p1o = tr(10, "LONG", None, "unresolved", 500, -0.30)
    rows2 = reconcile([s1], [p1o])
    assert rows2[0]["verdict"] == "open" and rows2[0]["patient_mae_pct"] == -30.0, rows2[0]

    psum = summarize_patient([p1, p2])
    assert psum["trades"] == 2 and psum["wins"] == 2
    assert psum["worst_mae_pct"] == -12.0 and psum["worst_mae_r"] == -2.4
    assert psum["hostage"]["dir"] == "LONG"
    # match verdict when outcomes are within 0.05R
    assert reconcile([s2], [tr(20, "SHORT", 2.02, "reversion", 5, -0.01)])[0]["verdict"] == "match"
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
