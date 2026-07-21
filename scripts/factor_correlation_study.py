"""Factor-correlation study — statistical grounding for confluence weighting.

RESEARCH ONLY. No trades, no strategy module, no database. Computes four
confluence factors on every closed bar of frozen ~5,000-bar 1H and 4H BTC
histories, correlates them with forward log returns on a 70/30 chronological
exploration/holdout split, evaluates a bounded pre-registered family of
boolean factor combinations on the exploration split, and tests exactly ONE
pre-registered candidate rule on the holdout. All cells are reported,
including nulls; a null result is a valid outcome.

The constants block below IS the pre-registration: it is committed before
`--phase explore` ever runs, and the findings doc quotes it verbatim
(docs/FACTOR_CORRELATION_STUDY.md section 2).

Usage (from the repo root):

    python scripts/factor_correlation_study.py --phase selftest
    python scripts/factor_correlation_study.py --phase fetch
    python scripts/factor_correlation_study.py --phase explore --tf both
    python scripts/factor_correlation_study.py --phase holdout

`--phase holdout` refuses to run twice (write-once output file) unless
`--force` is passed, and exits immediately while CANDIDATE_RULE is None.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from data.feed import Candle, fetch_candles  # noqa: E402
from strategy.atr import wilder_atr  # noqa: E402
from strategy.bias_4h import compute_bias  # noqa: E402
from strategy.ichimoku import ichimoku_components  # noqa: E402
from strategy.signals import _nearest_resistance, _nearest_support  # noqa: E402
from strategy.timeframes import interval_seconds  # noqa: E402
from strategy.trigger_1h import fisher_transform  # noqa: E402

# ── Section 0: PRE-REGISTERED CONSTANTS ─────────────────────────────────
# Frozen (committed) before any exploration result is computed. Changing
# anything here after exploration has run invalidates the study.

COIN = "BTC"
TIMEFRAMES = ("1h", "4h")
SPLIT_FRACTION = 0.70
# Forward-return horizons in bars, per timeframe — grounded by live
# backtest_trades hold data (1H-trigger median 2 / mean 4.8 bars held;
# 4H-trigger median 5.5 / mean 6.2): the pairs bracket actual hold times.
HORIZONS: dict[str, tuple[int, int]] = {"1h": (4, 12), "4h": (2, 6)}
ROW_START = 120            # unified warm-up (production WARMUP_BIAS_BARS)
LOOKBACK_BARS = 300        # per-bar structure/ichimoku slice (backtest.py)
FISHER_PERIOD = 10
ATR_PERIOD = 14
FRACTAL_WIDTH = 2
SR_LOOKBACK = 20
ICHIMOKU_VARIANT = "standard"

# Base binarizations: (factor key, operator, threshold). Round numbers,
# fixed a priori; |Fisher| >= 2.0 is the repo's established "extended"
# threshold (strategy/signals.py FISHER4H_EXHAUSTION_THRESHOLD).
THRESHOLDS: dict[str, tuple[str, str, float]] = {
    "F1_near_support":    ("f1", "<=", 0.25),
    "F1_near_resistance": ("f1", ">=", 0.75),
    "F2_fisher_above_rline": ("f2", ">", 0.0),
    "F2_fisher_below_rline": ("f2", "<", 0.0),
    "F3_above_cloud":     ("f3", ">", 0.0),
    "F3_below_cloud":     ("f3", "<", 0.0),
    "F4_extended_low":    ("f4", "<=", -2.0),
    "F4_extended_high":   ("f4", ">=", 2.0),
}
EXPECTED_CELLS = 64        # 8 singles + 24 cross-factor pairs + 32 triples

MIN_CELL_N = 30                    # exploration eligibility floor
MIN_PROJECTED_HOLDOUT_FIRINGS = 20  # fire-rate x holdout rows floor
N_SHIFTS = 200                     # circular-shift max-|t| calibration
SHIFT_SEED = 20260709
CALIBRATION_PCTL = 0.95

# Mechanical candidate selection (pre-registered — replaces a human review
# gate per user decision): among cells with exploration n >= MIN_CELL_N and
# projected holdout firings >= MIN_PROJECTED_HOLDOUT_FIRINGS, pick the single
# (tf, N, cell) with the highest |t_NW| that (a) exceeds its panel's
# circular-shift 95th-percentile max-|t| calibration bar and (b) has a
# same-sign conditional mean at the sibling horizon of the same timeframe.
# If none qualifies: no candidate, the holdout never runs, and the study
# reports a null result.
SELECTION_CRITERIA = (
    "highest |t_NW| among cells with n>=30 and projected holdout firings>=20, "
    "requiring |t_NW| > panel shift-calibration 95th-pct bar AND same-sign "
    "mean at the sibling horizon of the same timeframe"
)
# Holdout support criteria (pre-registered): conditional mean has the same
# sign as in exploration AND |t_NW| >= 2.0 on the holdout split.
HOLDOUT_SUPPORT_CRITERIA = "same sign as exploration AND |t_NW| >= 2.0 on holdout"

# Filled ONLY after exploration results are committed, before the single
# holdout run. Shape:
# {"tf": "4h", "n": 6, "conditions": ["F4_extended_low", "F3_above_cloud"],
#  "direction": "long", "exploration_mean": 0.0123, "exploration_t_nw": 3.4}
CANDIDATE_RULE: dict | None = None

# Data/output dirs are overridable via env so an extended candle dataset can be used for
# research WITHOUT touching the frozen research/data snapshots. Unset = current behavior
# (the audit reproduces against the frozen snapshots deterministically).
DATA_DIR = Path(os.environ.get("BTC_DATA_DIR", str(REPO_ROOT / "research" / "data")))
OUTPUT_DIR = Path(os.environ.get("BTC_OUTPUT_DIR", str(REPO_ROOT / "research" / "output")))


# ── Section 1: data layer ───────────────────────────────────────────────

def snapshot_path(tf: str) -> Path:
    return DATA_DIR / f"{COIN}_{tf}_snapshot.json"


def fetch_and_snapshot(tf: str) -> dict:
    """Pull the full retained history (~5,000 bars) once and freeze it,
    including the 70/30 split index, so the holdout boundary can never
    drift as Hyperliquid's rolling retention window advances."""
    step_ms = interval_seconds(tf) * 1000
    now_ms = int(time.time() * 1000)
    candles = fetch_candles(COIN, tf, now_ms - 5100 * step_ms, now_ms)
    n = len(candles)
    if n < 4900:
        raise RuntimeError(f"{tf}: only {n} candles returned — expected ~5000")
    gaps = [
        j for j in range(1, n)
        if candles[j].open_time_ms != candles[j - 1].open_time_ms + step_ms
    ]
    if gaps:
        raise RuntimeError(f"{tf}: {len(gaps)} gaps in candle series (first at index {gaps[0]})")

    split_index = math.floor(SPLIT_FRACTION * n)
    doc = {
        "coin": COIN,
        "interval": tf,
        "source": "hyperliquid candleSnapshot",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bar_count": n,
        "split_fraction": SPLIT_FRACTION,
        "split_index": split_index,
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


def load_snapshot(tf: str) -> tuple[list[Candle], int]:
    doc = json.loads(snapshot_path(tf).read_text(encoding="utf-8"))
    candles = [Candle(*row) for row in doc["candles"]]
    return candles, doc["split_index"]


def _ms_to_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


# ── Section 2: factor layer ─────────────────────────────────────────────
# Fisher and ATR are causal recursive filters — full-series precompute is
# lookahead-safe. Structure (compute_bias) and Ichimoku are computed on a
# fresh trailing slice per bar: fractal swings only confirm FRACTAL_WIDTH
# bars after the fact, so indexing a full-series precompute of structure
# WOULD repaint. Per-bar slicing is mandatory for F1/F3, not a style choice.

def build_factor_table(candles: list[Candle]) -> list[dict]:
    n = len(candles)
    fisher, trigger = fisher_transform(candles, FISHER_PERIOD)
    atr = wilder_atr(candles, ATR_PERIOD)
    assert ROW_START >= max(FISHER_PERIOD, ATR_PERIOD, 78), "warm-up must cover every factor"

    rows: list[dict] = []
    for i in range(ROW_START, n):
        window = candles[max(0, i - LOOKBACK_BARS + 1): i + 1]
        close = candles[i].close

        # F1: close position within the local S/R range, same-TF structure.
        f1: float | None = None
        bias_result = compute_bias(window, fractal_width=FRACTAL_WIDTH, sr_lookback=SR_LOOKBACK)
        ns = _nearest_support(bias_result, close)
        nr = _nearest_resistance(bias_result, close)
        if ns is not None and nr is not None and nr > ns:
            f1 = (close - ns) / (nr - ns)

        # F2: Fisher minus its 1-bar-delayed trigger line (the "R-line").
        f2: float | None = fisher[i] - trigger[i] if i >= FISHER_PERIOD else None

        # F3: signed ATR-normalized distance to the displaced cloud.
        f3: float | None = None
        atr_val = atr[i] if i >= ATR_PERIOD else 0.0
        _, _, cloud_top, cloud_bottom = ichimoku_components(window, ICHIMOKU_VARIANT)
        if cloud_top is not None and cloud_bottom is not None and atr_val > 0:
            if close > cloud_top:
                f3 = (close - cloud_top) / atr_val
            elif close < cloud_bottom:
                f3 = (close - cloud_bottom) / atr_val
            else:
                f3 = 0.0

        # F4: raw Fisher level.
        f4: float | None = fisher[i] if i >= FISHER_PERIOD - 1 else None

        rows.append({
            "i": i,
            "close_time_ms": candles[i].close_time_ms,
            "close": close,
            "f1": f1, "f2": f2, "f3": f3, "f4": f4,
        })
    return rows


def forward_log_returns(candles: list[Candle], horizon: int) -> list[float | None]:
    n = len(candles)
    out: list[float | None] = [None] * n
    for i in range(n - horizon):
        out[i] = math.log(candles[i + horizon].close / candles[i].close)
    return out


# ── Section 3: stats layer (pure Python, self-tested) ───────────────────

def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def average_ranks(xs: list[float]) -> list[float]:
    """1-based ranks with ties averaged."""
    order = sorted(range(len(xs)), key=lambda k: xs[k])
    ranks = [0.0] * len(xs)
    j = 0
    while j < len(order):
        k = j
        while k + 1 < len(order) and xs[order[k + 1]] == xs[order[j]]:
            k += 1
        avg = (j + k) / 2 + 1  # average of 1-based positions j+1..k+1
        for pos in range(j, k + 1):
            ranks[order[pos]] = avg
        j = k + 1
    return ranks


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def spearman(xs: list[float], ys: list[float]) -> float:
    return pearson(average_ranks(xs), average_ranks(ys))


@dataclass(frozen=True)
class CellStats:
    n: int
    mean: float
    hit_rate: float      # fraction of fired rows with forward return > 0
    se_nw: float
    t_nw: float


def nw_conditional_mean(fired: list[int], returns: list[float], lag: int) -> CellStats:
    """Newey–West (Bartlett) t-stat for the conditional mean of `returns`
    over row positions `fired`, treating non-fired rows as u=0 on the full
    row-ordered series (correct handling of irregular firings). lag=0
    reduces exactly to the classical SE — that identity is self-tested."""
    m = len(fired)
    if m == 0:
        return CellStats(0, 0.0, 0.0, float("inf"), 0.0)
    vals = [returns[p] for p in fired]
    mu = mean(vals)
    if m == 1:
        return CellStats(1, mu, 1.0 if vals[0] > 0 else 0.0, float("inf"), 0.0)
    u = {p: returns[p] - mu for p in fired}
    var = sum(v * v for v in u.values())  # C_0
    for l in range(1, lag + 1):
        w = 1 - l / (lag + 1)
        cl = 0.0
        for p in fired:
            uj = u.get(p + l)
            if uj is not None:
                cl += u[p] * uj
        var += 2 * w * cl
    se = math.sqrt(var) / m if var > 0 else float("inf")
    t = mu / se if math.isfinite(se) and se > 0 else 0.0
    hit = sum(1 for v in vals if v > 0) / m
    return CellStats(m, mu, hit, se, t)


def quintile_table(pairs: list[tuple[float, float]]) -> list[dict]:
    """pairs = (factor value, forward return); breakpoints from these rows
    only (exploration split). Returns 5 rows of {q, n, mean_fwd, lo, hi}."""
    if len(pairs) < 25:
        return []
    vals = sorted(p[0] for p in pairs)
    cuts = [vals[math.ceil(k / 5 * len(vals)) - 1] for k in (1, 2, 3, 4)]
    buckets: list[list[float]] = [[] for _ in range(5)]
    bounds: list[list[float]] = [[math.inf, -math.inf] for _ in range(5)]
    for fv, r in pairs:
        q = sum(1 for c in cuts if fv > c)
        buckets[q].append(r)
        bounds[q][0] = min(bounds[q][0], fv)
        bounds[q][1] = max(bounds[q][1], fv)
    return [
        {"q": q + 1, "n": len(b), "mean_fwd": mean(b) if b else 0.0,
         "lo": bounds[q][0] if b else None, "hi": bounds[q][1] if b else None}
        for q, b in enumerate(buckets)
    ]


def phase_subsample_stats(fired: list[int], returns: list[float], horizon: int) -> list[dict]:
    """Non-overlapping robustness: split fired rows by row-position phase
    mod `horizon`; targets within a phase share no bars. Naive t per phase."""
    out = []
    for offset in range(horizon):
        sel = [returns[p] for p in fired if p % horizon == offset]
        if len(sel) < 2:
            out.append({"offset": offset, "n": len(sel), "mean": None, "t": None})
            continue
        mu = mean(sel)
        sd = math.sqrt(sum((v - mu) ** 2 for v in sel) / (len(sel) - 1))
        se = sd / math.sqrt(len(sel))
        out.append({"offset": offset, "n": len(sel), "mean": mu,
                    "t": mu / se if se > 0 else 0.0})
    return out


# ── Section 4: combination layer ────────────────────────────────────────

def factor_of(cond: str) -> str:
    return THRESHOLDS[cond][0]


def enumerate_cells() -> list[tuple[str, ...]]:
    """8 singles + all cross-factor 2-ANDs + all cross-factor 3-ANDs = 64.
    Same-factor combinations are excluded (contradictory or redundant)."""
    conds = list(THRESHOLDS)
    cells: list[tuple[str, ...]] = [(c,) for c in conds]
    for k in (2, 3):
        for combo in combinations(conds, k):
            if len({factor_of(c) for c in combo}) == k:
                cells.append(combo)
    assert len(cells) == EXPECTED_CELLS, f"cell family is {len(cells)}, expected {EXPECTED_CELLS}"
    return cells


def condition_array(rows: list[dict], cond: str) -> list[bool | None]:
    """Trinary per-row evaluation: True / False / None (factor undefined).
    A row with an undefined constituent factor can never fire a cell."""
    key, op, thr = THRESHOLDS[cond]
    out: list[bool | None] = []
    for row in rows:
        v = row[key]
        if v is None:
            out.append(None)
        elif op == "<=":
            out.append(v <= thr)
        elif op == ">=":
            out.append(v >= thr)
        elif op == "<":
            out.append(v < thr)
        else:  # ">"
            out.append(v > thr)
    return out


def fired_positions(cell: tuple[str, ...], arrays: dict[str, list[bool | None]],
                    n_rows: int) -> list[int]:
    return [p for p in range(n_rows) if all(arrays[c][p] is True for c in cell)]


def shift_calibration(arrays: dict[str, list[bool | None]], returns: list[float],
                      cells: list[tuple[str, ...]], lag: int) -> list[float]:
    """Circular-shift max-|t| null distribution: rotate all 8 base condition
    arrays together (preserving inter-factor structure) by each of N_SHIFTS
    seeded offsets, recompute all 64 cells, record the max |t_NW| per shift."""
    n_rows = len(returns)
    rng = random.Random(SHIFT_SEED)
    offsets = rng.sample(range(1, n_rows), min(N_SHIFTS, n_rows - 1))
    maxima: list[float] = []
    for s in offsets:
        rotated = {c: arr[s:] + arr[:s] for c, arr in arrays.items()}
        best = 0.0
        for cell in cells:
            fired = fired_positions(cell, rotated, n_rows)
            if len(fired) < MIN_CELL_N:
                continue
            stats = nw_conditional_mean(fired, returns, lag)
            best = max(best, abs(stats.t_nw))
        maxima.append(best)
    return sorted(maxima)


def calibration_bar(maxima: list[float]) -> float:
    if not maxima:
        return float("inf")
    return maxima[min(len(maxima) - 1, math.ceil(CALIBRATION_PCTL * len(maxima)) - 1)]


# ── Section 5: phase drivers ────────────────────────────────────────────

def panel_rows(table: list[dict], split_index: int, n_bars: int, horizon: int,
               split: str) -> list[dict]:
    """Exploration rows carry an N-bar purge so no exploration target reaches
    into the holdout; holdout factors may look back across the boundary
    (backward-looking history is not leakage) but targets stay inside."""
    if split == "explore":
        return [r for r in table if r["i"] <= split_index - 1 - horizon]
    return [r for r in table if split_index <= r["i"] <= n_bars - 1 - horizon]


def analyze_panel(table: list[dict], candles: list[Candle], split_index: int,
                  horizon: int, split: str, run_calibration: bool) -> dict:
    rows = panel_rows(table, split_index, len(candles), horizon, split)
    if split == "explore":
        assert all(r["i"] + horizon < split_index for r in rows), "exploration target leaks into holdout"
    fwd = forward_log_returns(candles, horizon)
    returns = [fwd[r["i"]] for r in rows]
    assert all(v is not None for v in returns)
    lag = horizon - 1
    n_rows = len(rows)

    # Per-factor correlations + quintiles (exploration diagnostics).
    factors = {}
    for key in ("f1", "f2", "f3", "f4"):
        pairs = [(r[key], ret) for r, ret in zip(rows, returns) if r[key] is not None]
        entry: dict = {"defined": len(pairs), "missing": n_rows - len(pairs)}
        if len(pairs) >= 25:
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            entry["spearman"] = spearman(xs, ys)
            entry["pearson"] = pearson(xs, ys)
            entry["n_eff"] = len(pairs) / horizon
            entry["quintiles"] = quintile_table(pairs)
            if key == "f3":
                inside = sum(1 for x in xs if x == 0.0)
                entry["inside_cloud_frac"] = inside / len(xs)
                nz = [(x, y) for x, y in pairs if x != 0.0]
                if len(nz) >= 25:
                    entry["spearman_excl_inside"] = spearman([p[0] for p in nz], [p[1] for p in nz])
        factors[key] = entry

    # 64-cell combination table.
    cells = enumerate_cells()
    arrays = {c: condition_array(rows, c) for c in THRESHOLDS}
    cell_results = []
    for cell in cells:
        fired = fired_positions(cell, arrays, n_rows)
        stats = nw_conditional_mean(fired, returns, lag)
        cell_results.append({
            "conditions": list(cell),
            "n": stats.n,
            "fire_rate": stats.n / n_rows,
            "mean": stats.mean,
            "hit_rate": stats.hit_rate,
            "t_nw": stats.t_nw,
        })
    exceed = sum(1 for c in cell_results if abs(c["t_nw"]) > 2.0 and c["n"] >= MIN_CELL_N)

    panel = {
        "horizon": horizon,
        "split": split,
        "rows": n_rows,
        "lag": lag,
        "factors": factors,
        "cells": cell_results,
        "exceedance_gt2": exceed,
        "exceedance_expected_by_chance": round(EXPECTED_CELLS * 0.046, 1),
    }
    if run_calibration:
        maxima = shift_calibration(arrays, returns, cells, lag)
        panel["calibration_maxima_pctls"] = {
            "p50": maxima[len(maxima) // 2],
            "p95": calibration_bar(maxima),
            "max": maxima[-1],
        }
        panel["calibration_bar"] = calibration_bar(maxima)
    return panel


def mechanical_selection(results: dict[str, dict]) -> dict | None:
    """Apply SELECTION_CRITERIA across every (tf, horizon) panel. Returns the
    winning candidate descriptor or None (null result)."""
    best: dict | None = None
    for tf, tf_res in results.items():
        panels = {p["horizon"]: p for p in tf_res["panels"]}
        for horizon, panel in panels.items():
            sibling = next(p for h, p in panels.items() if h != horizon)
            sib_cells = {tuple(c["conditions"]): c for c in sibling["cells"]}
            hold_rows_est = tf_res["holdout_rows_estimate"][str(horizon)]
            for cell in panel["cells"]:
                if cell["n"] < MIN_CELL_N:
                    continue
                projected = cell["fire_rate"] * hold_rows_est
                if projected < MIN_PROJECTED_HOLDOUT_FIRINGS:
                    continue
                if abs(cell["t_nw"]) <= panel["calibration_bar"]:
                    continue
                sib = sib_cells[tuple(cell["conditions"])]
                if sib["n"] == 0 or (sib["mean"] > 0) != (cell["mean"] > 0):
                    continue
                if best is None or abs(cell["t_nw"]) > abs(best["exploration_t_nw"]):
                    best = {
                        "tf": tf,
                        "n": horizon,
                        "conditions": cell["conditions"],
                        "direction": "long" if cell["mean"] > 0 else "short",
                        "exploration_mean": cell["mean"],
                        "exploration_t_nw": cell["t_nw"],
                        "exploration_n": cell["n"],
                        "projected_holdout_firings": round(projected, 1),
                        "calibration_bar": panel["calibration_bar"],
                    }
    return best


def phase_fetch(tfs: list[str]) -> None:
    for tf in tfs:
        doc = fetch_and_snapshot(tf)
        print(f"{tf}: {doc['bar_count']} bars  {doc['first_close_utc']} .. {doc['last_close_utc']}")
        print(f"    split_index={doc['split_index']} (last exploration close {doc['split_close_utc']})")
        print(f"    -> {snapshot_path(tf)}")


def phase_explore(tfs: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_results: dict[str, dict] = {}
    for tf in tfs:
        candles, split_index = load_snapshot(tf)
        n_bars = len(candles)
        print(f"\n=== {tf}: building factor table ({n_bars} bars) ===")
        table = build_factor_table(candles)
        tf_res: dict = {
            "tf": tf,
            "bar_count": n_bars,
            "split_index": split_index,
            "row_start": ROW_START,
            "panels": [],
            "holdout_rows_estimate": {},
        }
        for horizon in HORIZONS[tf]:
            hold_rows = len(panel_rows(table, split_index, n_bars, horizon, "holdout"))
            tf_res["holdout_rows_estimate"][str(horizon)] = hold_rows
            print(f"--- panel {tf} N={horizon}: analyzing (calibration {N_SHIFTS} shifts) ---")
            panel = analyze_panel(table, candles, split_index, horizon, "explore",
                                  run_calibration=True)
            tf_res["panels"].append(panel)
            print(_panel_summary(tf, panel))
        out = OUTPUT_DIR / f"explore_{tf}.json"
        out.write_text(json.dumps(tf_res, indent=1), encoding="utf-8")
        print(f"written: {out}")
        all_results[tf] = tf_res

    if set(tfs) == set(TIMEFRAMES):
        candidate = mechanical_selection(all_results)
        print("\n=== MECHANICAL SELECTION (pre-registered criteria) ===")
        print(SELECTION_CRITERIA)
        if candidate is None:
            print("RESULT: no cell qualifies -> NO CANDIDATE (null result; holdout will not run)")
        else:
            print("RESULT: " + json.dumps(candidate, indent=1))
            print("Set CANDIDATE_RULE to this dict, commit, then run --phase holdout.")


def phase_holdout(force: bool) -> None:
    if CANDIDATE_RULE is None:
        print("CANDIDATE_RULE is None — set it (committed) before running the holdout. Exiting.")
        sys.exit(1)
    tf = CANDIDATE_RULE["tf"]
    horizon = CANDIDATE_RULE["n"]
    out_path = OUTPUT_DIR / f"holdout_{tf}.json"
    if out_path.exists() and not force:
        print(f"{out_path} already exists — the holdout is a ONE-SHOT test. Refusing to re-run "
              "(--force overrides, which invalidates the study's holdout guarantee).")
        sys.exit(1)

    candles, split_index = load_snapshot(tf)
    table = build_factor_table(candles)
    rows = panel_rows(table, split_index, len(candles), horizon, "holdout")
    fwd = forward_log_returns(candles, horizon)
    returns = [fwd[r["i"]] for r in rows]
    arrays = {c: condition_array(rows, c) for c in THRESHOLDS}
    fired = fired_positions(tuple(CANDIDATE_RULE["conditions"]), arrays, len(rows))
    stats = nw_conditional_mean(fired, returns, horizon - 1)
    phases = phase_subsample_stats(fired, returns, horizon)

    same_sign = (stats.mean > 0) == (CANDIDATE_RULE["exploration_mean"] > 0) and stats.n > 0
    supported = same_sign and abs(stats.t_nw) >= 2.0
    result = {
        "candidate": CANDIDATE_RULE,
        "holdout_rows": len(rows),
        "n": stats.n,
        "mean": stats.mean,
        "hit_rate": stats.hit_rate,
        "t_nw": stats.t_nw,
        "phase_subsamples": phases,
        "support_criteria": HOLDOUT_SUPPORT_CRITERIA,
        "supported": supported,
        "ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    print(f"\nVERDICT: {'SUPPORTED' if supported else 'NOT SUPPORTED'} "
          f"({HOLDOUT_SUPPORT_CRITERIA})")
    print(f"written (write-once): {out_path}")


def _panel_summary(tf: str, panel: dict) -> str:
    lines = [f"panel {tf} N={panel['horizon']}: rows={panel['rows']}"]
    for key, f in panel["factors"].items():
        if "spearman" in f:
            lines.append(
                f"  {key}: defined={f['defined']} missing={f['missing']} "
                f"spearman={f['spearman']:+.4f} pearson={f['pearson']:+.4f} n_eff~{f['n_eff']:.0f}"
            )
        else:
            lines.append(f"  {key}: defined={f['defined']} (too few for correlation)")
    eligible = [c for c in panel["cells"] if c["n"] >= MIN_CELL_N]
    top = sorted(eligible, key=lambda c: -abs(c["t_nw"]))[:3]
    for c in top:
        lines.append(
            f"  top cell: {'+'.join(c['conditions'])}  n={c['n']} mean={c['mean']:+.5f} "
            f"hit={c['hit_rate']:.2f} t_nw={c['t_nw']:+.2f}"
        )
    lines.append(
        f"  |t|>2 cells (n>={MIN_CELL_N}): {panel['exceedance_gt2']} "
        f"(~{panel['exceedance_expected_by_chance']} expected by chance); "
        f"calibration bar (p95 max|t|): {panel.get('calibration_bar', float('nan')):.2f}"
    )
    return "\n".join(lines)


# ── selftest ────────────────────────────────────────────────────────────

def phase_selftest() -> None:
    # Pearson/Spearman exactness.
    assert abs(pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) - 1.0) < 1e-12
    assert abs(pearson([1, 2, 3, 4, 5], [-1, -2, -3, -4, -5]) + 1.0) < 1e-12
    assert abs(spearman([1, 2, 3], [1, 3, 2]) - 0.5) < 1e-12
    assert abs(spearman([1.0, 2.0, 4.0, 8.0], [1, 2, 3, 4]) - 1.0) < 1e-12  # monotone nonlinear
    # Tie handling: hand-computed rho = 4 / (2*sqrt(5)).
    assert abs(spearman([1, 1, 2, 2], [1, 2, 3, 4]) - 4 / (2 * math.sqrt(5))) < 1e-12

    # NW lag=0 == classical (population) SE.
    vals = [1.0, 2.0, 4.0, 3.0, 5.0, 2.5]
    st = nw_conditional_mean(list(range(len(vals))), vals, lag=0)
    mu = mean(vals)
    se_classical = math.sqrt(sum((v - mu) ** 2 for v in vals)) / len(vals)
    assert abs(st.se_nw - se_classical) < 1e-12

    # Overlapping MA(N-1) series: NW SE must exceed classical SE materially.
    rng = random.Random(42)
    noise = [rng.gauss(0.0, 1.0) for _ in range(2050)]
    horizon = 4
    r = [sum(noise[i:i + horizon]) + 0.05 for i in range(2000)]  # overlapping sums + drift
    st_nw = nw_conditional_mean(list(range(len(r))), r, lag=horizon - 1)
    st_cl = nw_conditional_mean(list(range(len(r))), r, lag=0)
    assert st_nw.se_nw > 1.3 * st_cl.se_nw, (st_nw.se_nw, st_cl.se_nw)
    assert abs(st_nw.t_nw) < abs(st_cl.t_nw)

    # Cell family arithmetic.
    cells = enumerate_cells()
    assert len(cells) == 64
    assert sum(1 for c in cells if len(c) == 1) == 8
    assert sum(1 for c in cells if len(c) == 2) == 24
    assert sum(1 for c in cells if len(c) == 3) == 32

    # Quintiles: monotone factor -> monotone means, breakpoints exploration-only.
    pairs = [(float(k), float(k) / 100) for k in range(100)]
    qt = quintile_table(pairs)
    assert [row["n"] for row in qt] == [20] * 5
    assert all(qt[k]["mean_fwd"] < qt[k + 1]["mean_fwd"] for k in range(4))

    # Trinary conditions: None can never fire.
    rows = [{"f1": None, "f2": 1.0, "f3": 0.5, "f4": -2.5}]
    arr = condition_array(rows, "F1_near_support")
    assert arr == [None]
    assert fired_positions(("F1_near_support", "F4_extended_low"),
                           {"F1_near_support": [None], "F4_extended_low": [True]}, 1) == []

    print("selftest: all assertions passed")


# ── main ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", required=True,
                        choices=("fetch", "selftest", "explore", "holdout"))
    parser.add_argument("--tf", default="both", choices=("1h", "4h", "both"))
    parser.add_argument("--force", action="store_true",
                        help="override the holdout write-once guard (invalidates the one-shot guarantee)")
    args = parser.parse_args()
    tfs = list(TIMEFRAMES) if args.tf == "both" else [args.tf]

    if args.phase == "selftest":
        phase_selftest()
    elif args.phase == "fetch":
        phase_fetch(tfs)
    elif args.phase == "explore":
        phase_explore(tfs)
    else:
        phase_holdout(args.force)


if __name__ == "__main__":
    main()
