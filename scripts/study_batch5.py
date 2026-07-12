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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=("sf",))
    args = ap.parse_args()
    if args.phase == "sf":
        phase_sf()


if __name__ == "__main__":
    main()
