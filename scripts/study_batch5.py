"""Study Batch 5 driver. S-F first (block-boot bars, DSR, N_eff, pooling),
then S-A/S-D/S-B/S-C/S-E/S-G. Reuses existing strategy code and frozen
snapshots; pure Python. See docs/STUDY_BATCH5.md for the registration.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import OUTPUT_DIR, load_snapshot  # noqa: E402
from strategy_tournament import (  # noqa: E402
    BARS_PER_YEAR, STRATEGIES, WARMUP, buy_hold_metrics, eval_bounds,
    log_returns, metrics, net_strategy_returns,
)
from breadth_tournament import UNIVERSE  # noqa: E402
import blockstats as bs  # noqa: E402

MEAN_BLOCK_DAYS = 20
REPS = 10000
# existing (shift-null) bars + observed best Sharpe, for the old-vs-new table
OLD = {
    "BTC_1d":   {"bar": 1.40, "best_variant": "tsmom30", "best_sharpe": 0.77, "bpy": 365.0},
    "BTC_12h":  {"bar": 1.59, "best_variant": "sma200",  "best_sharpe": 0.91, "bpy": 730.0},
    "breadth":  {"bar": 2.05, "best_variant": "tsmom30", "best_sharpe": 0.78, "bpy": 365.0},
}


def _sharpe_se(sr_ann, n, bpy):
    sr = sr_ann / math.sqrt(bpy)
    return math.sqrt(bpy) * math.sqrt((1 + 0.5 * sr * sr) / n)


def _single_asset_panel(tf):
    """Recompute the 7-variant exploration-window Sharpes + block-boot family
    bar for a single-asset tournament panel (BTC 1d / 12h)."""
    candles, _ = load_snapshot(tf)
    rets = log_returns(candles)
    bpy = BARS_PER_YEAR[tf]
    a, ee, _ = eval_bounds(len(candles))
    mean_block = MEAN_BLOCK_DAYS * (bpy / 365.0)   # bars per ~20 days
    pos_by = {name: fn(candles) for name, fn in STRATEGIES.items()}
    sharpes = {}
    net_streams = {}
    for name, pos in pos_by.items():
        net = net_strategy_returns(pos, rets)
        sharpes[name] = metrics(net, pos, a, ee, bpy)["sharpe"]
        net_streams[name] = net[a:ee + 1]
    # block-boot family bar over the exploration window
    expl_rets = rets[a:ee + 1]
    expl_pos = [pos_by[n][a:ee + 1] for n in STRATEGIES]
    bar = bs.block_bootstrap_family_bar(expl_rets, expl_pos, bpy, mean_block, REPS)
    best = max(sharpes, key=sharpes.get)
    n_obs = ee - a + 1
    dsr = bs.deflated_sharpe_ratio(sharpes[best], net_streams[best], bpy, len(STRATEGIES))
    return {"panel": tf, "sharpes": {k: round(v, 3) for k, v in sharpes.items()},
            "best_variant": best, "best_sharpe": round(sharpes[best], 3),
            "n_obs": n_obs, "block_bar": bar, "deflated_sharpe": round(dsr, 3),
            "net_streams": net_streams}


def _breadth_panel():
    """7-asset EW portfolio — reuses breadth_tournament's exact observed
    computation (fee-inclusive, exploration split) so the observed Sharpe
    matches the doc, then a fee-consistent block-boot null: resample the
    common-bar RETURN index jointly across sleeves, keep positions & fees
    fixed, recompute each variant's portfolio Sharpe, family-max 95th pct."""
    from breadth_tournament import (build_universe, sleeve_series, port_metrics,
                                    split_bounds, FEE)
    uni = build_universe()
    common = uni["common_ts"]
    n = len(common)
    ee, _ = split_bounds(n)                       # exploration = [0, ee]
    pos_all = {name: {c: STRATEGIES[name](uni["per_asset"][c]["candles"]) for c in UNIVERSE}
               for name in STRATEGIES}
    sharpes = {}
    for name in STRATEGIES:
        port, _ = sleeve_series(uni, pos_all[name])
        sharpes[name] = port_metrics(port, 0, ee)["sharpe"]
    # aligned per-sleeve (positions-into-bar, returns) over the exploration window
    ret_by = {c: [] for c in UNIVERSE}
    posA = {name: {c: [] for c in UNIVERSE} for name in STRATEGIES}
    for c in UNIVERSE:
        p = uni["per_asset"][c]
        idx = [p["eligible"][common[i]] for i in range(ee + 1)]
        ret_by[c] = [p["rets"][j] for j in idx]
        for name in STRATEGIES:
            posA[name][c] = [pos_all[name][c][j] for j in idx]
    m = ee + 1
    rng = random.Random(20260712)
    maxima = []
    for _ in range(REPS):
        rsi = bs.stationary_bootstrap_indices(m, MEAN_BLOCK_DAYS, rng)
        best = -1e9
        for name in STRATEGIES:
            net = []
            for i in range(1, m):
                gross = sum(posA[name][c][i - 1] * ret_by[c][rsi[i]] for c in UNIVERSE)
                fee = sum(FEE * abs(posA[name][c][i] - posA[name][c][i - 1]) for c in UNIVERSE)
                net.append((gross - fee) / len(UNIVERSE))
            best = max(best, bs.annualized_sharpe(net, 365.0))
        maxima.append(best)
    maxima.sort()
    bar = maxima[min(len(maxima) - 1, math.ceil(0.95 * len(maxima)) - 1)]
    best = max(sharpes, key=sharpes.get)
    return {"panel": "breadth", "sharpes": {k: round(v, 3) for k, v in sharpes.items()},
            "best_variant": best, "best_sharpe": round(sharpes[best], 3),
            "n_obs": m, "block_bar": {"bar": round(bar, 3),
            "null_median": round(maxima[len(maxima) // 2], 3), "reps": REPS},
            "ret_by": ret_by, "common_len": n}


def _load_alt(coin):
    p = Path(__file__).resolve().parents[1] / "research" / "data" / f"{coin}_1d_snapshot.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    from data.feed import Candle
    return [Candle(*row) for row in doc["candles"]], doc.get("split_index", 0)


def phase_sf():
    out = {"panels": [], "effective_bets": {}, "hierarchical": {}, "track4": {}, "engine": {}}
    print("=== S-F: block-bootstrap re-report (10k reps, mean block ~20d) ===")

    panels = [_single_asset_panel("1d"), _single_asset_panel("12h"), _breadth_panel()]
    keymap = {"1d": "BTC_1d", "12h": "BTC_12h", "breadth": "breadth"}
    for p in panels:
        key = keymap[p["panel"]]
        old = OLD[key]
        new_bar = p["block_bar"]["bar"]
        obs = p["best_sharpe"]
        clears = obs > new_bar
        verdict_new = "POSITIVE" if clears else "NULL"
        print(f"\n{key}: best {p['best_variant']} Sharpe {obs:.2f} | "
              f"OLD shift-bar {old['bar']} (was NULL) -> NEW block-bar {new_bar} "
              f"=> {verdict_new} (DSR {p.get('deflated_sharpe','n/a')})")
        out["panels"].append({"panel": key, "best_variant": p["best_variant"],
                              "best_sharpe": obs, "old_bar": old["bar"],
                              "new_block_bar": new_bar, "old_verdict": "NULL",
                              "new_verdict": verdict_new,
                              "deflated_sharpe": p.get("deflated_sharpe"),
                              "null_median": p["block_bar"].get("null_median")})

    # effective bets — 7 assets (daily returns) and 7 BTC trend streams
    btc = panels[0]
    asset_streams = []
    breadth = panels[2]
    common_len = breadth["common_len"]
    for coin in UNIVERSE:
        asset_streams.append(breadth["ret_by"][coin][-min(common_len, 1200):])
    R_assets = bs.correlation_matrix(asset_streams)
    R_streams = bs.correlation_matrix([btc["net_streams"][n] for n in STRATEGIES])
    out["effective_bets"] = {"assets": bs.effective_bets(R_assets),
                             "trend_streams": bs.effective_bets(R_streams)}
    print(f"\neffective bets — 7 assets: {out['effective_bets']['assets']}")
    print(f"effective bets — 7 trend streams: {out['effective_bets']['trend_streams']}")

    # hierarchical pooling — per-asset tsmom30 Sharpe -> common trend effect
    ests, ses = [], []
    for coin in UNIVERSE:
        candles = (load_snapshot("1d")[0] if coin == "BTC" else _load_alt(coin)[0])
        rets = log_returns(candles)
        a, ee, _ = eval_bounds(len(candles))
        from strategy_tournament import tsmom_positions
        pos = tsmom_positions(candles, 30)
        net = net_strategy_returns(pos, rets)
        sr = metrics(net, pos, a, ee, 365.0)["sharpe"]
        ests.append(sr); ses.append(_sharpe_se(sr, ee - a + 1, 365.0))
    hp = bs.hierarchical_pool(ests, ses)
    out["hierarchical"] = {"per_asset_tsmom30_sharpe": [round(e, 3) for e in ests],
                           "common_mu": round(hp["common_mu"], 3),
                           "common_sd": round(hp["common_sd"], 3),
                           "ci95": [round(hp["ci95"][0], 3), round(hp["ci95"][1], 3)],
                           "tau": round(hp["tau"], 3),
                           "prob_positive": round(hp["prob_positive"], 4)}
    print(f"\nhierarchical pooling (per-asset tsmom30 Sharpe): common mu "
          f"{out['hierarchical']['common_mu']} sd {out['hierarchical']['common_sd']} "
          f"CI95 {out['hierarchical']['ci95']} P(>0)={out['hierarchical']['prob_positive']}")

    # Track 4 robust cell (-1.25) as a per-bar strategy Sharpe + block bar + DSR
    from track4_mean_reversion import run_config, bias_direction_series
    from strategy.trigger_1h import fisher_transform
    c4, _ = load_snapshot("4h")
    bc, _ = load_snapshot("12h")
    dirs, btimes = bias_direction_series(bc, 30)
    fisher = fisher_transform(c4)[0]
    trades = run_config(c4, fisher, dirs, btimes, 1.25, None, long_only=True,
                        exit_mode="first_profit", atr_series=None)
    pos4 = [0] * len(c4)
    for t in trades:
        for k in range(t["entry_i"], t["exit_i"] + 1 if t.get("exit_i") else t["entry_i"] + 1):
            if k < len(pos4):
                pos4[k] = 1
    rets4 = log_returns(c4)
    a4 = WARMUP + 1
    net4 = net_strategy_returns(pos4, rets4)
    sr4 = bs.annualized_sharpe(net4[a4:], 6 * 365.0)
    bar4 = bs.block_bootstrap_family_bar(rets4[a4:], [pos4[a4:]], 6 * 365.0, 20 * 6, REPS)
    dsr4 = bs.deflated_sharpe_ratio(sr4, net4[a4:], 6 * 365.0, 24)  # ~24 Track-4 cells tried
    out["track4"] = {"sharpe": round(sr4, 3), "block_bar": bar4,
                     "deflated_sharpe": round(dsr4, 3), "trades": len(trades),
                     "verdict": "POSITIVE" if sr4 > bar4["bar"] else "NULL"}
    print(f"\nTrack 4 -1.25: Sharpe {sr4:.2f} | block-bar {bar4['bar']} | "
          f"DSR {dsr4:.3f} => {out['track4']['verdict']}")

    # live engine (4h/1h fib-extension) — 8 corrected trades (CORRECTED_BASELINE_4H1H.md).
    # Trade-based R, n=8: below the DSR/Sharpe-bar minimum, so an iid bootstrap
    # CI on mean R is the honest read; flagged underpowered.
    engine_r = [-1.49, 2.17, -1.46, 2.39, 1.96, -1.99, -1.73, 3.01]
    rng_e = random.Random(20260712)
    means = sorted(sum(rng_e.choice(engine_r) for _ in engine_r) / len(engine_r) for _ in range(REPS))
    ci = (round(means[int(0.025 * REPS)], 2), round(means[int(0.975 * REPS)], 2))
    out["engine"] = {"n_trades": len(engine_r), "mean_r": round(sum(engine_r) / len(engine_r), 3),
                     "total_r": round(sum(engine_r), 2), "boot_ci95_mean_r": ci,
                     "verdict": "PENDING (n=8 underpowered; forward test is the arbiter)"}
    print(f"\nlive engine: {len(engine_r)} trades, mean R {out['engine']['mean_r']} "
          f"(total {out['engine']['total_r']}R), iid-boot 95% CI on mean R {ci} "
          f"-> PENDING (n=8 underpowered)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # strip bulky arrays before writing
    for p in panels:
        p.pop("net_streams", None); p.pop("ret_by", None)
    (OUTPUT_DIR / "batch5_sf.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\nwritten: research/output/batch5_sf.json")


def _track4_series():
    from track4_mean_reversion import bias_direction_series
    from strategy.trigger_1h import fisher_transform
    from strategy.atr import wilder_atr
    c4, _ = load_snapshot("4h")
    bc, _ = load_snapshot("12h")
    dirs, btimes = bias_direction_series(bc, 30)
    fisher = fisher_transform(c4)[0]
    atr = wilder_atr(c4)
    return c4, dirs, btimes, fisher, atr


def _run_sa_cell(c4, dirs, btimes, fisher, atr, stop_mult, target_mode):
    """One S-A cell. stop_mult in {None,2.5,3.5}; target_mode in
    {'first_profit',0.5,1.0,1.5}. R distance = (stop_mult or 3.5)*ATR@entry;
    no-stop cells report R-equiv vs 3.5*ATR. Long-only, exit = first of
    {stop, R-target/first_profit, Fisher>=+1.5}."""
    from bisect import bisect_right
    FEE = 0.00075
    WARM = 60
    n = len(c4)
    trades, pos = [], [0] * n
    open_t = None
    for i in range(WARM, n):
        c = c4[i]
        if open_t is not None:
            e, stop, tgt, rdist = open_t["entry"], open_t["stop"], open_t["target"], open_t["rdist"]
            open_t["mae"] = min(open_t["mae"], c.low / e - 1)
            exit_px = reason = None
            if stop is not None and c.low <= stop:
                exit_px, reason = stop, "stop"
            elif tgt is not None and c.high >= tgt:
                exit_px, reason = tgt, "target"
            elif target_mode == "first_profit" and (c.close / e - 1) - 2 * FEE > 0:
                exit_px, reason = c.close, "first_profit"
            elif fisher[i] >= 1.5:
                exit_px, reason = c.close, "fisher_reversal"
            if exit_px is not None:
                net = (exit_px / e - 1) - 2 * FEE
                open_t.update(exit_i=i, net_pct=net * 100, r=net / (rdist / e),
                              bars_held=i - open_t["entry_i"], exit_reason=reason)
                trades.append(open_t)
                for k in range(open_t["entry_i"], i + 1):
                    pos[k] = 1
                open_t = None
            continue
        bj = bisect_right(btimes, c.close_time_ms) - 1
        b = dirs[bj] if bj >= 0 else 0
        if fisher[i] <= -1.25 and b == 1 and atr[i] > 0:
            rdist = (stop_mult or 3.5) * atr[i]
            stop = c.close - stop_mult * atr[i] if stop_mult else None
            tgt = c.close + target_mode * rdist if target_mode != "first_profit" else None
            open_t = {"entry_i": i, "entry": c.close, "stop": stop, "target": tgt,
                      "rdist": rdist, "mae": 0.0}
    return trades, pos


def phase_sa():
    c4, dirs, btimes, fisher, atr = _track4_series()
    rets4 = log_returns(c4)
    a4 = 61
    ppy = 6 * 365.0
    stops = [(None, "none"), (2.5, "2.5xATR"), (3.5, "3.5xATR")]
    targets = [("first_profit", "first_profit"), (0.5, "+0.5R"), (1.0, "+1.0R"), (1.5, "+1.5R")]
    print("=== S-A: Track 4 joint stop x target grid (adjudicates Comp NULL) ===")
    cells, any_stopped_survives = [], False
    for sm, sl in stops:
        for tm, tl in targets:
            trades, pos = _run_sa_cell(c4, dirs, btimes, fisher, atr, sm, tm)
            nets = [t["net_pct"] for t in trades]
            rs = [t["r"] for t in trades]
            wins = sum(1 for x in nets if x > 0)
            gl = abs(sum(r for r in rs if r <= 0))
            gw = sum(r for r in rs if r > 0)
            net_pos = sum(nets) > 0
            sharpe = bs.annualized_sharpe(net_strategy_returns(pos, rets4)[a4:], ppy)
            bar = bs.block_bootstrap_family_bar(rets4[a4:], [pos[a4:]], ppy, 20 * 6, REPS)["bar"]
            stopped = sm is not None
            passes = stopped and net_pos and sharpe > bar
            if passes:
                any_stopped_survives = True
            cells.append({"stop": sl, "target": tl, "stopped": stopped,
                          "trades": len(trades), "wins": wins,
                          "sum_net_pct": round(sum(nets), 2), "sum_r": round(sum(rs), 2),
                          "pf": round(gw / gl, 2) if gl > 0 else None,
                          "worst_mae_pct": round(min((t["mae"] for t in trades), default=0) * 100, 2),
                          "sharpe": round(sharpe, 3), "block_bar": round(bar, 3),
                          "net_positive": net_pos, "kill_pass": passes})
            print(f"  stop {sl:8} tgt {tl:12}: n={len(trades):2d} W={wins:2d} "
                  f"netR {sum(rs):+6.2f} net% {sum(nets):+7.2f} PF {cells[-1]['pf']} "
                  f"Sharpe {sharpe:+.2f} vs bar {bar:.2f} worstMAE {cells[-1]['worst_mae_pct']}%"
                  + ("  <-- STOPPED CELL SURVIVES" if passes else ""))
    verdict = ("Comp NULL PREMATURE (>=1 stopped cell positive net AND clears block-boot bar)"
               if any_stopped_survives else "Comp NULL CONFIRMED (no stopped cell survives)")
    print(f"\nVERDICT: {verdict}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "batch5_sa.json").write_text(json.dumps(
        {"cells": cells, "any_stopped_survives": any_stopped_survives,
         "verdict": verdict}, indent=1), encoding="utf-8")
    print("written: research/output/batch5_sa.json")


def _boot_ci_mean(xs, mean_block_obs=8, reps=2000, seed=20260712):
    """Stationary block-bootstrap 95% CI on the mean of a time-ordered
    (autocorrelated/overlapping) observation sequence."""
    if len(xs) < 3:
        return (None, None)
    rng = random.Random(seed)
    n = len(xs)
    means = sorted(sum(xs[k] for k in bs.stationary_bootstrap_indices(n, mean_block_obs, rng)) / n
                   for _ in range(reps))
    return (round(means[int(0.025 * reps)] * 100, 3), round(means[int(0.975 * reps)] * 100, 3))


def phase_sd():
    from track4_mean_reversion import bias_direction_series  # noqa (kept parallel imports)
    from strategy.trigger_1h import fisher_transform
    c4, _ = load_snapshot("4h")
    fisher = fisher_transform(c4)[0]
    closes = [c.close for c in c4]
    n = len(c4)
    print("=== S-D: reversion asymmetry diagnostic (no trading rule) ===")
    rows = []
    for X in (1.0, 1.25, 1.5):
        for H in (6, 24, 72):
            long_fwd, short_fwd = [], []
            for i in range(60, n - H):
                fwd = closes[i + H] / closes[i] - 1
                if fisher[i] <= -X:
                    long_fwd.append(fwd)          # oversold -> expect reversion UP
                elif fisher[i] >= X:
                    short_fwd.append(fwd)         # overbought -> expect reversion DOWN
            lm = sum(long_fwd) / len(long_fwd) if long_fwd else 0.0
            sm = sum(short_fwd) / len(short_fwd) if short_fwd else 0.0
            lci = _boot_ci_mean(long_fwd)
            sci = _boot_ci_mean(short_fwd)
            # reversion strength: long side = +mean (up move); short side = -mean (down move)
            rev_long, rev_short = lm, -sm
            rows.append({"fisher_thr": X, "horizon_bars": H,
                         "long_n": len(long_fwd), "long_mean_pct": round(lm * 100, 3),
                         "long_ci95": lci, "short_n": len(short_fwd),
                         "short_mean_pct": round(sm * 100, 3), "short_ci95": sci,
                         "reversion_long_pct": round(rev_long * 100, 3),
                         "reversion_short_pct": round(rev_short * 100, 3),
                         "asymmetry_pct": round((rev_long - rev_short) * 100, 3)})
            print(f"  |F|>={X} H={H:2d}b: LONG n={len(long_fwd):4d} mean {lm*100:+.3f}% CI{lci} | "
                  f"SHORT n={len(short_fwd):4d} mean {sm*100:+.3f}% CI{sci} | "
                  f"rev_long {rev_long*100:+.3f}% rev_short {rev_short*100:+.3f}% "
                  f"asym {(rev_long-rev_short)*100:+.3f}%")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "batch5_sd.json").write_text(json.dumps({"rows": rows}, indent=1), encoding="utf-8")
    print("written: research/output/batch5_sd.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=("sf", "sa", "sd"))
    args = ap.parse_args()
    {"sf": phase_sf, "sa": phase_sa, "sd": phase_sd}[args.phase]()


if __name__ == "__main__":
    main()
