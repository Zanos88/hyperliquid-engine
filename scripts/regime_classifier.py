"""Regime Classifier — Bull/Bear/Neutral, pre-registered and LOCKED.

RESEARCH ONLY. Composite daily regime label from three confirmed-free
components (Part A): price structure, halving-cycle phase, and funding. The
definition below IS the pre-registration — committed before any retroactive
strategy test (Part D), and never tuned after seeing results. If it doesn't
"work," that is a result, not a reason to iterate.

Combination is a fixed 2-of-3 majority; when funding abstains (no data before
2024-05, i.e. <365d of the 2023-05+ funding series) a directional label needs
BOTH remaining components to agree, else NEUTRAL.

Phases: selfcheck | instances (Part C) | apply (Part D).
Usage: python scripts/regime_classifier.py --phase selfcheck
"""
from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_ROOT))

from factor_correlation_study import DATA_DIR, OUTPUT_DIR, load_snapshot  # noqa: E402
from strategy.bias_4h import SwingDirection, detect_swings  # noqa: E402

# ── LOCKED registered constants (Part B) — never tuned after Part C/D ──
STRUCT_WINDOW = 120            # trailing daily bars for swing structure
FRACTAL_WIDTH = 2              # detect_swings default, reused
HALVINGS = (date(2020, 5, 11), date(2024, 4, 19))
# days-since-last-halving → phase (cycle ≈ 1400d). Heuristic UNDER TEST.
HALVING_BUCKETS = ((400, "BULL"), (550, "BEAR"), (1100, "NEUTRAL"), (10**9, "BULL"))
FUNDING_MA_DAYS = 30           # trailing average funding
FUNDING_PCTILE_WINDOW_DAYS = 365
FUNDING_BULL_PCTILE = 70.0
FUNDING_BEAR_PCTILE = 30.0
MIN_RUN_DAYS = 21              # Part C: ignore runs shorter than this
DAY_MS = 86_400_000

FUNDING_PATH = DATA_DIR / "BTC_funding_history.json"


# ── component votes ──

def structure_from_swings(swings) -> str:
    """HH+HL = BULL, LH+LL = BEAR, else NEUTRAL. Pure (testable) core."""
    highs = [s.end_price for s in swings if s.direction == SwingDirection.UP]
    lows = [s.end_price for s in swings if s.direction == SwingDirection.DOWN]
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"
    hh, hl = highs[-1] > highs[-2], lows[-1] > lows[-2]
    lh, ll = highs[-1] < highs[-2], lows[-1] < lows[-2]
    if hh and hl:
        return "BULL"
    if lh and ll:
        return "BEAR"
    return "NEUTRAL"


def structure_vote(window_candles) -> str:
    return structure_from_swings(detect_swings(window_candles, fractal_width=FRACTAL_WIDTH))


def halving_vote(bar_date: date) -> str:
    prior = [h for h in HALVINGS if h <= bar_date]
    if not prior:
        return "NEUTRAL"          # before the first in-record halving (n/a in window)
    days = (bar_date - max(prior)).days
    for bound, label in HALVING_BUCKETS:
        if days < bound:
            return label
    return "NEUTRAL"


def _funding_daily_avgs(candles, funding_rows) -> list[float | None]:
    ftimes = [t for t, _ in funding_rows]
    fvals = [v for _, v in funding_rows]
    ms30 = FUNDING_MA_DAYS * DAY_MS
    out: list[float | None] = []
    for c in candles:
        ce = c.close_time_ms
        lo, hi = bisect_left(ftimes, ce - ms30), bisect_right(ftimes, ce)
        win = fvals[lo:hi]
        out.append(sum(win) / len(win) if win else None)
    return out


def funding_votes(candles, funding_rows) -> list[str | None]:
    """Trailing-30d avg funding, percentile within its trailing-365d own
    distribution. ABSTAINS (None) until 365d of funding history exists."""
    if not funding_rows:
        return [None] * len(candles)
    fstart = funding_rows[0][0]
    ms365 = FUNDING_PCTILE_WINDOW_DAYS * DAY_MS
    daily = _funding_daily_avgs(candles, funding_rows)
    votes: list[str | None] = []
    for i, c in enumerate(candles):
        ce = c.close_time_ms
        if ce < fstart + ms365 or daily[i] is None:
            votes.append(None)
            continue
        lo_ms = ce - ms365
        window = [daily[j] for j in range(i + 1)
                  if daily[j] is not None and candles[j].close_time_ms >= lo_ms]
        cur = daily[i]
        pct = 100.0 * sum(1 for v in window if v <= cur) / len(window)
        votes.append("BULL" if pct >= FUNDING_BULL_PCTILE
                     else "BEAR" if pct <= FUNDING_BEAR_PCTILE else "NEUTRAL")
    return votes


def combine(structure: str, halving: str, funding: str | None) -> str:
    """2-of-3 majority among non-abstaining components; if funding abstains,
    the two remaining must agree for a directional label, else NEUTRAL."""
    votes = [v for v in (structure, halving, funding) if v is not None]
    if votes.count("BULL") >= 2:
        return "BULL"
    if votes.count("BEAR") >= 2:
        return "BEAR"
    return "NEUTRAL"


def _bar_date(close_ms: int) -> date:
    return datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc).date()


def classify(candles, funding_rows) -> list[dict]:
    fvotes = funding_votes(candles, funding_rows)
    out = []
    for i, c in enumerate(candles):
        window = candles[max(0, i - STRUCT_WINDOW + 1): i + 1]
        s = structure_vote(window)
        h = halving_vote(_bar_date(c.close_time_ms))
        f = fvotes[i]
        out.append({"close_ms": c.close_time_ms, "date": _bar_date(c.close_time_ms).isoformat(),
                    "label": combine(s, h, f), "structure": s, "halving": h, "funding": f})
    return out


def load_funding_rows() -> list[tuple[int, float]]:
    if not FUNDING_PATH.exists():
        return []
    doc = json.loads(FUNDING_PATH.read_text(encoding="utf-8"))
    return [(int(t), float(v)) for t, v in doc["rows"]]


# ── phases ──

def phase_labels() -> None:
    """Emit BTC per-bar labels (Part B artifact — inspectable definition)."""
    candles, _ = load_snapshot("1d")
    labels = classify(candles, load_funding_rows())
    counts = {k: sum(1 for r in labels if r["label"] == k) for k in ("BULL", "BEAR", "NEUTRAL")}
    print(f"BTC 1d {len(labels)} bars ({labels[0]['date']} .. {labels[-1]['date']}) | {counts}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "regime_labels_btc.json").write_text(json.dumps(
        {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "locked_definition": {
             "structure": f"detect_swings trailing {STRUCT_WINDOW}d, HH+HL=BULL / LH+LL=BEAR",
             "halving": {"halvings": [h.isoformat() for h in HALVINGS], "buckets": HALVING_BUCKETS},
             "funding": f"{FUNDING_MA_DAYS}d avg pctile in {FUNDING_PCTILE_WINDOW_DAYS}d; "
                        f">={FUNDING_BULL_PCTILE} BULL / <={FUNDING_BEAR_PCTILE} BEAR; "
                        "abstains <365d history",
             "combination": "2-of-3 majority; funding-abstain -> 2-of-2 must agree"},
         "counts": counts, "labels": labels}, indent=1), encoding="utf-8")
    print(f"written: {OUTPUT_DIR / 'regime_labels_btc.json'}")


PANEL = ("ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK")
EPISODE_GAP_DAYS = 90          # Part C reporting: merge same-label runs closer than this


def load_asset_1d(coin: str):
    from data.feed import Candle
    doc = json.loads((DATA_DIR / f"{coin}_1d_snapshot.json").read_text(encoding="utf-8"))
    return [Candle(*row) for row in doc["candles"]]


def _runs_and_episodes(labels, target, min_run=MIN_RUN_DAYS, gap=EPISODE_GAP_DAYS):
    """Maximal contiguous runs of `target` (>= min_run bars), then merge runs
    separated by <= gap bars of other labels into distinct episodes."""
    runs, s = [], None
    for i, r in enumerate(labels):
        if r["label"] == target:
            s = i if s is None else s
        elif s is not None:
            if i - s >= min_run:
                runs.append((s, i - 1))
            s = None
    if s is not None and len(labels) - s >= min_run:
        runs.append((s, len(labels) - 1))
    episodes = []
    for a, b in runs:
        if episodes and a - episodes[-1][1] <= gap:
            episodes[-1] = (episodes[-1][0], b)
        else:
            episodes.append((a, b))
    fmt = lambda a, b: {"from": labels[a]["date"], "to": labels[b]["date"], "days": b - a + 1}
    return [fmt(a, b) for a, b in runs], [fmt(a, b) for a, b in episodes]


def phase_instances() -> None:
    funding = load_funding_rows()
    out = {}
    print(f"regime instances (min run {MIN_RUN_DAYS}d, episode-merge gap {EPISODE_GAP_DAYS}d)\n")
    for coin in ("BTC",) + PANEL:
        candles = load_snapshot("1d")[0] if coin == "BTC" else load_asset_1d(coin)
        # panel assets have NO per-asset funding frozen -> funding abstains (structure+halving)
        labels = classify(candles, funding if coin == "BTC" else [])
        bull_runs, bull_eps = _runs_and_episodes(labels, "BULL")
        bear_runs, bear_eps = _runs_and_episodes(labels, "BEAR")
        out[coin] = {"bull_runs": bull_runs, "bull_episodes": bull_eps,
                     "bear_runs": bear_runs, "bear_episodes": bear_eps}
        print(f"{coin:5} BULL: {len(bull_runs)} runs / {len(bull_eps)} episodes | "
              f"BEAR: {len(bear_runs)} runs / {len(bear_eps)} episodes")
        for e in bull_eps:
            print(f"       bull episode {e['from']} .. {e['to']} ({e['days']}d)")

    btc_bull_eps = len(out["BTC"]["bull_episodes"])
    panel_bull_eps = sum(len(out[c]["bull_episodes"]) for c in PANEL)
    gate = (f"BTC = {btc_bull_eps} independent bull episode(s). "
            + ("INSUFFICIENT: one bull episode cannot separate 'bull-market strategy' "
               "from 'that one lucky 2024-25 stretch' — Part D bull verdicts are capped "
               "at insufficient-data." if btc_bull_eps <= 1 else
               "Multiple bull episodes exist; regime dependence is testable, with care."))
    caveat = (f"Panel adds {panel_bull_eps} bull episodes across 6 alts, but they CO-MOVE "
              "(N_eff ~ 2 from the factor study) and share BTC's halving calendar + the same "
              "macro cycles - they are NOT 6 independent instances.")
    print(f"\nGATE: {gate}\n{caveat}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "regime_instances.json").write_text(json.dumps(
        {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "min_run_days": MIN_RUN_DAYS, "episode_gap_days": EPISODE_GAP_DAYS,
         "panel_funding": "abstains (no per-alt funding frozen; structure+halving only)",
         "gate": gate, "co_movement_caveat": caveat, "by_asset": out}, indent=1),
        encoding="utf-8")
    print(f"written: {OUTPUT_DIR / 'regime_instances.json'}")


REPS_D = 3000                  # block-boot reps for Part D (3 regime family bars)
MIN_REGIME_BARS = 30           # tournament: min in-regime bars to compute a cell
MIN_REGIME_TRADES = 10         # trade strategies: min per-regime trades to judge
REGIMES = ("BULL", "BEAR", "NEUTRAL")
N_TRIALS_TOURNAMENT = 21       # 7 variants × 3 regimes (regime filter counted as DoF)


def _apply_tournament(candles, labels) -> dict:
    from strategy_tournament import STRATEGIES, log_returns, net_strategy_returns
    from blockstats import annualized_sharpe, block_bootstrap_family_bar, deflated_sharpe_ratio
    rets = log_returns(candles)
    lab = [r["label"] for r in labels]
    pos_by = {name: fn(candles) for name, fn in STRATEGIES.items()}
    net_by = {name: net_strategy_returns(pos_by[name], rets) for name in STRATEGIES}
    out = {}
    for reg in REGIMES:
        idx = [j for j in range(1, len(candles)) if lab[j] == reg]
        if len(idx) < MIN_REGIME_BARS:
            out[reg] = {"n_bars": len(idx), "verdict": "insufficient-data"}
            continue
        r_reg = [rets[j] for j in idx]
        fam = [[pos_by[name][j - 1] for j in idx] for name in STRATEGIES]
        bar = block_bootstrap_family_bar(r_reg, fam, 365.0, 20.0, reps=REPS_D)["bar"]
        variants = {}
        for name in STRATEGIES:
            net_reg = [net_by[name][j] for j in idx]
            sr = annualized_sharpe(net_reg, 365.0)
            dsr = deflated_sharpe_ratio(sr, net_reg, 365.0, N_TRIALS_TOURNAMENT)
            variants[name] = {"sharpe": round(sr, 3), "dsr": round(dsr, 3),
                              "clears_family_bar": sr > bar}
        any_clear = any(v["clears_family_bar"] and v["dsr"] >= 0.95 for v in variants.values())
        out[reg] = {"n_bars": len(idx), "family_bar": round(bar, 3),
                    "any_variant_clears_and_dsr": any_clear, "variants": variants}
    return out


def _split_trades(trades, regime_by_date):
    split = {reg: [] for reg in REGIMES}
    for t in trades:
        d = t["entry_ts"][:10]
        split.setdefault(regime_by_date.get(d, "NEUTRAL"), []).append(t)
    return split


def _summ_trades(ts, gated) -> dict:
    if not ts:
        return {"n": 0, "verdict": "insufficient-data"}
    nets = [t["net_pct"] for t in ts]
    maes = [t.get("mae", 0.0) * 100 for t in ts]
    return {"n": len(ts), "wins": sum(1 for x in nets if x > 0),
            "sum_net_pct": round(sum(nets), 2),
            "worst_mae_pct": round(min(maes), 2) if maes else None,
            "verdict": "insufficient-data" if gated else "descriptive"}


def _apply_track4(regime_by_date) -> dict:
    from track4_mean_reversion import run_config, bias_direction_series
    from strategy.trigger_1h import fisher_transform
    c4h, _ = load_snapshot("4h")
    fisher = fisher_transform(c4h)[0]
    bc, _ = load_snapshot("12h")
    dirs, times = bias_direction_series(bc, 30)
    trades = run_config(c4h, fisher, dirs, times, 1.25, None,
                        long_only=True, exit_mode="first_profit")
    split = _split_trades(trades, regime_by_date)
    return {"config": "4h Fisher<=-1.25, 12h SMA30 bias, long-only, no-stop, first-profit",
            "total_trades": len(trades),
            "by_regime": {reg: _summ_trades(split[reg], len(split[reg]) < MIN_REGIME_TRADES)
                          for reg in REGIMES}}


def _apply_breakout(regime_by_date) -> dict:
    from breakout_continuation import (BIAS_METHODS, VOL_MULTS, bias_series_4h,
                                       run_cell_nostop, volume_floor)
    c4h, _ = load_snapshot("4h")
    floor = volume_floor(c4h)
    method, vm = BIAS_METHODS[0], VOL_MULTS[len(VOL_MULTS) // 2]
    signs, bms = bias_series_4h(c4h, method)
    trades = run_cell_nostop(c4h, "4h", signs, bms, vm, floor)
    split = _split_trades(trades, regime_by_date)
    return {"config": f"4h breakout (bias {method}, vol_mult {vm}), no-stop hold-to-profit",
            "total_trades": len(trades),
            "by_regime": {reg: _summ_trades(split[reg], len(split[reg]) < MIN_REGIME_TRADES)
                          for reg in REGIMES}}


def phase_apply() -> None:
    btc1d, _ = load_snapshot("1d")
    labels = classify(btc1d, load_funding_rows())
    regime_by_date = {r["date"]: r["label"] for r in labels}
    print(f"Part D: regime split (block-boot {REPS_D} reps, DSR n_trials {N_TRIALS_TOURNAMENT}); "
          "gate: BULL suggestive-only, BEAR insufficient-data (Part C)\n")

    tour = _apply_tournament(btc1d, labels)
    print("TREND TOURNAMENT (BTC 1d, per-bar block-boot + DSR):")
    for reg in REGIMES:
        c = tour[reg]
        if "variants" not in c:
            print(f"  {reg:7} n_bars {c['n_bars']:4} -> {c['verdict']}")
            continue
        best = max(c["variants"].items(), key=lambda kv: kv[1]["sharpe"])
        print(f"  {reg:7} n_bars {c['n_bars']:4} | family bar {c['family_bar']:+.2f} | "
              f"best {best[0]} Sharpe {best[1]['sharpe']:+.2f} DSR {best[1]['dsr']:.2f} "
              f"clears={best[1]['clears_family_bar']} | any_clear&DSR={c['any_variant_clears_and_dsr']}")

    t4 = _apply_track4(regime_by_date)
    bo = _apply_breakout(regime_by_date)
    for name, res in (("TRACK 4 -1.25", t4), ("S-B BREAKOUT", bo)):
        print(f"\n{name} ({res['total_trades']} trades total):")
        for reg in REGIMES:
            s = res["by_regime"][reg]
            if s["n"] == 0:
                print(f"  {reg:7} n=0 -> insufficient-data")
            else:
                print(f"  {reg:7} n={s['n']:2} wins {s['wins']} netP&L {s['sum_net_pct']:+.2f}% "
                      f"worstMAE {s['worst_mae_pct']}% -> {s['verdict']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "regime_split.json").write_text(json.dumps(
        {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "block_boot_reps": REPS_D, "dsr_n_trials_tournament": N_TRIALS_TOURNAMENT,
         "gate": "BULL suggestive-only, BEAR insufficient-data (Part C)",
         "tournament": tour, "track4_m125": t4, "breakout_sb": bo}, indent=1), encoding="utf-8")
    print(f"\nwritten: {OUTPUT_DIR / 'regime_split.json'}")


def phase_selfcheck() -> None:
    from strategy.bias_4h import Swing
    U, D = SwingDirection.UP, SwingDirection.DOWN
    # structure: HH+HL -> BULL, LH+LL -> BEAR, mixed -> NEUTRAL
    bull = [Swing(10, 20, U, 0), Swing(20, 15, D, 1), Swing(15, 30, U, 2),
            Swing(30, 25, D, 3), Swing(25, 40, U, 4)]
    bear = [Swing(40, 30, D, 0), Swing(30, 35, U, 1), Swing(35, 20, D, 2),
            Swing(20, 25, U, 3), Swing(25, 10, D, 4)]
    assert structure_from_swings(bull) == "BULL"
    assert structure_from_swings(bear) == "BEAR"
    assert structure_from_swings([Swing(10, 20, U, 0), Swing(20, 15, D, 1)]) == "NEUTRAL"  # <2 each
    # higher-high but lower-low (expanding) -> NEUTRAL
    assert structure_from_swings([Swing(10, 20, U, 0), Swing(20, 8, D, 1),
                                  Swing(8, 30, U, 2), Swing(30, 5, D, 3)]) == "NEUTRAL"
    # halving buckets (relative to 2024-04-19)
    from datetime import timedelta
    h = HALVINGS[1]
    assert halving_vote(h + timedelta(days=100)) == "BULL"      # expansion
    assert halving_vote(h + timedelta(days=450)) == "BEAR"      # peak-and-decline
    assert halving_vote(h + timedelta(days=700)) == "NEUTRAL"   # accumulation
    assert halving_vote(h + timedelta(days=1200)) == "BULL"     # pre-halving run-up
    assert halving_vote(date(2019, 1, 1)) == "NEUTRAL"          # before first halving
    # combination incl. funding abstain (2-of-2 fallback)
    assert combine("BULL", "BULL", None) == "BULL"
    assert combine("BULL", "BEAR", None) == "NEUTRAL"
    assert combine("BULL", "NEUTRAL", None) == "NEUTRAL"        # abstain -> needs both
    assert combine("BULL", "BULL", "BEAR") == "BULL"            # 2-of-3 majority
    assert combine("BULL", "BEAR", "NEUTRAL") == "NEUTRAL"
    assert combine("BEAR", "BEAR", "BULL") == "BEAR"
    # funding abstention: a bar within the first 365d of funding history -> None
    from data.feed import Candle
    fstart = 1_684_000_000_000
    rows = [(fstart + k * 3_600_000, 0.0001) for k in range(24 * 400)]
    early = Candle(fstart + 10 * DAY_MS, fstart + 10 * DAY_MS, 1, 1, 1, 1, 0)
    late = Candle(fstart + 400 * DAY_MS, fstart + 400 * DAY_MS, 1, 1, 1, 1, 0)
    fv = funding_votes([early, late], rows)
    assert fv[0] is None and fv[1] is not None, fv
    print("selfcheck: all assertions passed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--phase", required=True, choices=("selfcheck", "labels", "instances", "apply"))
    args = ap.parse_args()
    if args.phase == "selfcheck":
        phase_selfcheck()
    elif args.phase == "labels":
        phase_labels()
    elif args.phase == "instances":
        phase_instances()
    elif args.phase == "apply":
        phase_apply()


if __name__ == "__main__":
    main()
