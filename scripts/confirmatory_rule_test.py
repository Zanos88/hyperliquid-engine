"""Round-2 confirmatory tests of the "washed-out dip near support" rule.

RESEARCH ONLY. Three pre-registered one-shot tests of the single rule that
topped round 1's exploration (docs/FACTOR_CORRELATION_STUDY.md, 1H N=4 cell,
t_NW +2.59): fire long when Fisher <= -2.0 AND Fisher below its R-line AND
close in the bottom quarter of the local S/R range. No sweep: exactly three
Newey-West computations, on windows fixed below, at one pre-registered pass
bar. Everything statistical is imported unchanged from the round-1 module —
this script defines no new math and no new factor logic.

  Test 0 — 1H holdout  (direct confirmation: same TF as discovery,
                        genuinely unseen rows after 2026-05-07)
  Test 1 — 4H holdout  (generalization; round-1 exploration saw this rule
                        NEGATIVE on 4H — prior evidence is against a pass)
  Test 2 — 12H full    (generalization; series never fetched before round 2)

Usage (from the repo root):

    python scripts/confirmatory_rule_test.py --phase selfcheck
    python scripts/confirmatory_rule_test.py --phase fetch     # freeze 12H snapshot
    python scripts/confirmatory_rule_test.py --phase run       # ONE SHOT, all 3 tests

`--phase run` refuses to run if ANY output file already exists. There is
deliberately no --force: a re-run is a new study, not a reproduction.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import (  # noqa: E402  (also inserts repo root on sys.path)
    DATA_DIR,
    OUTPUT_DIR,
    ROW_START,
    THRESHOLDS,
    build_factor_table,
    condition_array,
    fired_positions,
    forward_log_returns,
    load_snapshot,
    nw_conditional_mean,
    phase_selftest,
    phase_subsample_stats,
    snapshot_path,
)
from data.feed import fetch_candles  # noqa: E402
from strategy.timeframes import interval_seconds  # noqa: E402

# ── PRE-REGISTERED PROTOCOL (round 2) ───────────────────────────────────
# Committed before any test runs. The rule is the round-1 discovery cell,
# verbatim — conditions resolve through round-1 THRESHOLDS, no redefinition.

RULE_CONDITIONS = ("F4_extended_low", "F2_fisher_below_rline", "F1_near_support")
RULE_DIRECTION = "long"
HORIZON = 4          # bars, ALL tests — identical to the discovery cell (1H N=4)
PASS_BAR_T = 2.0     # PASS iff mean > 0 AND t_NW >= 2.0 (sign-restricted)

# What the rule conditions must mean (guards against any round-1 edit drift).
EXPECTED_TRIPLES = {
    "F4_extended_low": ("f4", "<=", -2.0),
    "F2_fisher_below_rline": ("f2", "<", 0.0),
    "F1_near_support": ("f1", "<=", 0.25),
}

TESTS = (
    {"id": 0, "label": "Test 0 — 1H holdout (direct confirmation)", "tf": "1h", "window": "holdout"},
    {"id": 1, "label": "Test 1 — 4H holdout (generalization)", "tf": "4h", "window": "holdout"},
    {"id": 2, "label": "Test 2 — 12H full series (generalization)", "tf": "12h", "window": "full"},
)

MIN_12H_BARS = 3000  # history check saw 3,300; retention cap is 5,000


def out_path(tf: str) -> Path:
    return OUTPUT_DIR / f"confirm_{tf}.json"


def _ms_to_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def fetch_and_snapshot_12h() -> dict:
    """Freeze the 12H series in the round-1 snapshot format. Local variant
    because the round-1 fetch asserts ~5,000 bars (retention-capped series);
    12H history is shorter (~3,300 bars back to 2022-01)."""
    tf = "12h"
    step_ms = interval_seconds(tf) * 1000
    now_ms = int(time.time() * 1000)
    candles = fetch_candles("BTC", tf, now_ms - 5100 * step_ms, now_ms)
    n = len(candles)
    if n < MIN_12H_BARS:
        raise RuntimeError(f"{tf}: only {n} candles returned — expected ~3300")
    gaps = [
        j for j in range(1, n)
        if candles[j].open_time_ms != candles[j - 1].open_time_ms + step_ms
    ]
    if gaps:
        raise RuntimeError(f"{tf}: {len(gaps)} gaps in candle series (first at index {gaps[0]})")
    split_index = math.floor(0.70 * n)  # format compatibility; UNUSED this round
    doc = {
        "coin": "BTC",
        "interval": tf,
        "source": "hyperliquid candleSnapshot",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bar_count": n,
        "split_fraction": 0.70,
        "split_index": split_index,
        "split_index_note": "unused in round 2 — Test 2 is a single pre-registered test on the full series",
        "first_close_utc": _ms_to_utc(candles[0].close_time_ms),
        "split_close_utc": _ms_to_utc(candles[split_index].close_time_ms),
        "last_close_utc": _ms_to_utc(candles[-1].close_time_ms),
        "schema": ["open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"],
        "candles": [
            [c.open_time_ms, c.close_time_ms, c.open, c.high, c.low, c.close, c.volume]
            for c in candles
        ],
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path(tf).write_text(json.dumps(doc), encoding="utf-8")
    return doc


def run_one_test(test: dict) -> dict:
    tf = test["tf"]
    candles, split_index = load_snapshot(tf)
    n_bars = len(candles)
    table = build_factor_table(candles)
    if test["window"] == "holdout":
        rows = [r for r in table if split_index <= r["i"] <= n_bars - 1 - HORIZON]
    else:  # full series
        rows = [r for r in table if r["i"] <= n_bars - 1 - HORIZON]

    fwd = forward_log_returns(candles, HORIZON)
    returns = [fwd[r["i"]] for r in rows]
    assert all(v is not None for v in returns)
    arrays = {c: condition_array(rows, c) for c in RULE_CONDITIONS}
    fired = fired_positions(RULE_CONDITIONS, arrays, len(rows))
    stats = nw_conditional_mean(fired, returns, HORIZON - 1)
    phases = phase_subsample_stats(fired, returns, HORIZON)
    passed = stats.n > 0 and stats.mean > 0 and stats.t_nw >= PASS_BAR_T

    return {
        "label": test["label"],
        "tf": tf,
        "window": test["window"],
        "rule_conditions": list(RULE_CONDITIONS),
        "direction": RULE_DIRECTION,
        "horizon_bars": HORIZON,
        "window_first_close_utc": _ms_to_utc(rows[0]["close_time_ms"]),
        "window_last_close_utc": _ms_to_utc(rows[-1]["close_time_ms"]),
        "rows": len(rows),
        "uncond_mean": sum(returns) / len(returns),
        "n": stats.n,
        "fire_rate": stats.n / len(rows),
        "mean": stats.mean,
        "hit_rate": stats.hit_rate,
        "t_nw": stats.t_nw,
        "phase_subsamples": phases,
        "pass_criteria": f"mean > 0 AND t_NW >= {PASS_BAR_T}",
        "passed": passed,
        "ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def phase_selfcheck() -> None:
    for cond, triple in EXPECTED_TRIPLES.items():
        assert THRESHOLDS[cond] == triple, f"{cond}: THRESHOLDS drifted to {THRESHOLDS[cond]}"
    assert set(RULE_CONDITIONS) == set(EXPECTED_TRIPLES)
    phase_selftest()  # round-1 stats assertions
    existing = [t["tf"] for t in TESTS if out_path(t["tf"]).exists()]
    assert not existing, f"output files already exist for: {existing} — round 2 already ran"
    # 1H/4H snapshots must exist (Test 0/1 need them; no refetch this round).
    for tf in ("1h", "4h"):
        assert snapshot_path(tf).exists(), f"missing round-1 snapshot for {tf}"
    print("selfcheck: all assertions passed")


def phase_run() -> None:
    existing = [str(out_path(t["tf"])) for t in TESTS if out_path(t["tf"]).exists()]
    if existing:
        print("REFUSING to run: output files already exist (the three tests are ONE-SHOT; "
              "there is no --force — a re-run is a new study):")
        for p in existing:
            print(f"  {p}")
        sys.exit(1)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for test in TESTS:
        print(f"\n=== {test['label']} ===")
        result = run_one_test(test)
        out_path(test["tf"]).write_text(json.dumps(result, indent=1), encoding="utf-8")
        results.append(result)
        print(f"  window: {result['window_first_close_utc']} .. {result['window_last_close_utc']}"
              f"  rows={result['rows']}  uncond_mean={result['uncond_mean']:+.5f}")
        print(f"  n={result['n']}  fire_rate={100 * result['fire_rate']:.1f}%  "
              f"mean={result['mean']:+.5f}  hit={result['hit_rate']:.2f}  t_NW={result['t_nw']:+.2f}")
        pr = [p for p in result["phase_subsamples"] if p["mean"] is not None]
        if pr:
            print(f"  phase subsamples (n/mean): " +
                  ", ".join(f"{p['n']}/{p['mean']:+.5f}" for p in pr))
        print(f"  -> {'PASS' if result['passed'] else 'FAIL'}  ({result['pass_criteria']})")
        print(f"  written (write-once): {out_path(test['tf'])}")

    passes = sum(1 for r in results if r["passed"])
    print(f"\n=== FAMILY SUMMARY ===")
    print(f"{passes}/3 tests passed at the pre-registered bar (mean > 0 AND t_NW >= {PASS_BAR_T}).")
    print("Family false-positive context: per-test ~2.3% one-sided under the null; "
          "chance of >=1 false pass across the 3 (dependent) tests is at most ~6.7%.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", required=True, choices=("selfcheck", "fetch", "run"))
    args = parser.parse_args()
    if args.phase == "selfcheck":
        phase_selfcheck()
    elif args.phase == "fetch":
        doc = fetch_and_snapshot_12h()
        print(f"12h: {doc['bar_count']} bars  {doc['first_close_utc']} .. {doc['last_close_utc']}")
        print(f"    -> {snapshot_path('12h')}")
    else:
        phase_run()


if __name__ == "__main__":
    main()
