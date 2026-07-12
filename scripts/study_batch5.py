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


def phase_sb():
    """S-B: breakout re-test with wide/time-invalidation stops. 4H trigger,
    1D Fib-S/R HTF bias (higher TF for a 4H trigger), volume-confirmed
    (mult 2.0 fixed, 20th-pct floor). 6 cells = stops {2.0xATR, 3.0xATR,
    time-inval} x targets {2R, trail 2.5xATR}."""
    from bisect import bisect_right
    from breakout_continuation import confirmed_levels, bias_series_4h, volume_floor
    from strategy.trigger_1h import sma
    from strategy.atr import wilder_atr
    c4, _ = load_snapshot("4h")
    c1d, _ = load_snapshot("1d")
    signs, bms = bias_series_4h(c1d, "fibsr")            # 1D Fib-S/R HTF bias
    atr = wilder_atr(c4)
    vols = [c.volume for c in c4]
    vavg = sma(vols, 20)
    floor = volume_floor(c4)
    highs, lows = confirmed_levels(c4)
    n = len(c4)
    FEE, VMULT = 0.00075, 2.0
    ppy = 6 * 365.0
    rets4 = log_returns(c4)

    def run(stop_kind, stop_mult, target_kind):
        hi_c = lo_c = 0
        last_high = last_low = None
        trades, pos = [], [0] * n
        ot = None
        for i in range(60, n):
            c = c4[i]
            while hi_c < len(highs) and highs[hi_c][0] <= i:
                last_high = highs[hi_c][1]; hi_c += 1
            while lo_c < len(lows) and lows[lo_c][0] <= i:
                last_low = lows[lo_c][1]; lo_c += 1
            if ot is not None:
                e, sd, side = ot["entry"], ot["rdist"], ot["side"]
                if side == "LONG":
                    ot["mae"] = min(ot["mae"], c.low / e - 1)
                    ot["peak"] = max(ot["peak"], c.high)
                else:
                    ot["mae"] = min(ot["mae"], (e - c.high) / e)
                    ot["trough"] = min(ot["trough"], c.low)
                held = i - ot["entry_i"]
                exit_px = reason = None
                if stop_kind == "price":
                    lvl = e - stop_mult * ot["atr"] if side == "LONG" else e + stop_mult * ot["atr"]
                    if (side == "LONG" and c.low <= lvl) or (side == "SHORT" and c.high >= lvl):
                        exit_px, reason = lvl, "stop"
                if exit_px is None and target_kind == "trail":
                    if side == "LONG":
                        tr = ot["peak"] - 2.5 * ot["atr"]
                        if c.low <= tr and held > 0:
                            exit_px, reason = tr, "trail"
                    else:
                        tr = ot["trough"] + 2.5 * ot["atr"]
                        if c.high >= tr and held > 0:
                            exit_px, reason = tr, "trail"
                if exit_px is None and target_kind == "2R":
                    tgt = e + 2 * sd if side == "LONG" else e - 2 * sd
                    if (side == "LONG" and c.high >= tgt) or (side == "SHORT" and c.low <= tgt):
                        exit_px, reason = tgt, "target"
                if exit_px is None and stop_kind == "time_inval" and held >= 12:
                    prog = (ot["peak"] - e) if side == "LONG" else (e - ot["trough"])
                    if prog < 0.5 * sd:
                        exit_px, reason = c.close, "time_inval"
                if exit_px is not None:
                    g = (exit_px / e - 1) if side == "LONG" else (e - exit_px) / e
                    net = g - 2 * FEE
                    ot.update(exit_i=i, net_pct=net * 100, r=net / (sd / e),
                              bars_held=held, exit_reason=reason)
                    trades.append(ot)
                    for k in range(ot["entry_i"], i + 1):
                        pos[k] = 1 if side == "LONG" else -1
                    ot = None
                continue
            bj = bisect_right(bms, c.close_time_ms) - 1
            b = signs[bj] if bj >= 0 else 0
            if atr[i] <= 0 or vavg[i] <= 0 or not (vols[i] >= VMULT * vavg[i] and vols[i] >= floor):
                continue
            prev = c4[i - 1].close
            side = level = None
            if b == 1 and last_high is not None and prev <= last_high < c.close:
                side, level = "LONG", last_high
            elif b == -1 and last_low is not None and prev >= last_low > c.close:
                side, level = "SHORT", last_low
            if side:
                rdist = (stop_mult if stop_kind == "price" else 2.0) * atr[i]
                ot = {"entry_i": i, "entry": c.close, "side": side, "atr": atr[i],
                      "rdist": rdist, "mae": 0.0, "peak": c.close, "trough": c.close}
        return trades, pos

    stops = [("price", 2.0, "2.0xATR"), ("price", 3.0, "3.0xATR"), ("time_inval", None, "time-inval")]
    targets = [("2R", "2R"), ("trail", "trail2.5ATR")]
    print("=== S-B: breakout wide-stop / time-invalidation re-test (4H, Fib-S/R 1D bias) ===")
    cells, any_survive = [], False
    for sk, sm, slabel in stops:
        for tk, tlabel in targets:
            trades, pos = run(sk, sm, tk)
            nets = [t["net_pct"] for t in trades]
            rs = [t["r"] for t in trades]
            net_pos = sum(nets) > 0
            gl = abs(sum(r for r in rs if r <= 0)); gw = sum(r for r in rs if r > 0)
            netstream = net_strategy_returns(pos, rets4)[61:]  # signed pos (short = -1)
            sharpe = bs.annualized_sharpe(netstream, ppy)
            bar = bs.block_bootstrap_family_bar(rets4[61:], [pos[61:]], ppy, 20 * 6, REPS)["bar"]
            dsr = bs.deflated_sharpe_ratio(sharpe, netstream, ppy, 6)   # 6 S-B cells
            max_hold = max((t["bars_held"] for t in trades), default=0)
            worst_mae = round(min((t["mae"] for t in trades), default=0) * 100, 2)
            passes_bar = net_pos and sharpe > bar
            passes_dsr = not math.isnan(dsr) and dsr >= 0.95
            any_survive = any_survive or (passes_bar and passes_dsr)
            cells.append({"stop": slabel, "target": tlabel, "trades": len(trades),
                          "wins": sum(1 for x in nets if x > 0), "sum_net_pct": round(sum(nets), 2),
                          "sum_r": round(sum(rs), 2), "pf": round(gw / gl, 2) if gl > 0 else None,
                          "sharpe": round(sharpe, 3), "block_bar": round(bar, 3),
                          "deflated_sharpe": round(dsr, 3), "worst_mae_pct": worst_mae,
                          "max_hold_bars": max_hold, "max_hold_days": round(max_hold / 6, 1),
                          "net_positive": net_pos, "clears_block_bar": passes_bar,
                          "clears_dsr": passes_dsr,
                          "time_inval_exits": sum(1 for t in trades if t["exit_reason"] == "time_inval")})
            note = ""
            if passes_bar and not passes_dsr:
                note = "  <-- clears block-bar but DSR REJECTS"
            elif passes_bar and passes_dsr:
                note = "  <-- SURVIVES (bar + DSR)"
            print(f"  {slabel:11} {tlabel:12}: n={len(trades):3d} W={cells[-1]['wins']:3d} "
                  f"netR {sum(rs):+7.2f} net% {sum(nets):+8.2f} PF {cells[-1]['pf']} "
                  f"Sharpe {sharpe:+.2f} vs bar {bar:.2f} DSR {dsr:.3f} maxHold {round(max_hold/6,0):.0f}d{note}")
    verdict = ("POSITIVE — >=1 cell positive net AND clears block-boot bar" if any_survive
               else "NULL — archetype closed with the geometry objection tested")
    print(f"\nVERDICT: {verdict}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "batch5_sb.json").write_text(json.dumps(
        {"cells": cells, "verdict": verdict}, indent=1), encoding="utf-8")
    print("written: research/output/batch5_sb.json")


def _breadth_reversal_returns(active_by_bar=None):
    """S-C/S-G breadth: weekly (7-bar) rebalance, long the bottom-2 assets by
    trailing 56-day return, inverse-realized-vol weighted, flat otherwise.
    Returns (portfolio_daily_returns, ew_buyhold_daily_returns) over the common
    window. active_by_bar (S-G): optional predicate(common_index)->bool gating
    weeks (flat when inactive)."""
    from breadth_tournament import build_universe
    uni = build_universe()
    common = uni["common_ts"]
    n = len(common)
    ret_by, close_by = {}, {}
    for c in UNIVERSE:
        p = uni["per_asset"][c]
        idx = [p["eligible"][common[i]] for i in range(n)]
        ret_by[c] = [p["rets"][j] for j in idx]
        close_by[c] = [p["candles"][j].close for j in idx]
    L, VOLW = 56, 30
    port, ewbh = [0.0] * n, [0.0] * n
    weights = {c: 0.0 for c in UNIVERSE}
    for i in range(1, n):
        if i % 7 == 0 and i > L:                # weekly rebalance
            active = active_by_bar(i) if active_by_bar else True
            if not active:
                weights = {c: 0.0 for c in UNIVERSE}
            else:
                trail = {c: close_by[c][i] / close_by[c][i - L] - 1 for c in UNIVERSE}
                bottom2 = sorted(trail, key=trail.get)[:2]
                vols = {c: (sum(r * r for r in ret_by[c][i - VOLW:i]) / VOLW) ** 0.5 for c in bottom2}
                inv = {c: (1.0 / vols[c] if vols[c] > 0 else 0.0) for c in bottom2}
                s = sum(inv.values()) or 1.0
                weights = {c: (inv[c] / s if c in bottom2 else 0.0) for c in UNIVERSE}
        port[i] = sum(weights[c] * ret_by[c][i] for c in UNIVERSE)
        ewbh[i] = sum(ret_by[c][i] for c in UNIVERSE) / len(UNIVERSE)
    return port, ewbh, L


def _maxdd(rets):
    eq = peak = mdd = 0.0
    for r in rets:
        eq += r; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    return mdd


def phase_sc():
    c1d, _ = load_snapshot("1d")
    closes = [c.close for c in c1d]
    lows = [c.low for c in c1d]
    rets = log_returns(c1d)
    n = len(c1d)
    ppy = 365.0
    print("=== S-C: medium-horizon reversal (8-10wk gap) ===")
    cells = []
    for L in (56, 70):
        trail = [closes[i] / closes[i - L] - 1 if i >= L else None for i in range(n)]
        for P in (10, 20):
            for H in (14, 21):
                pos = [0] * n
                trades = []
                i = L + 730
                while i < n - H:
                    win = [trail[j] for j in range(i - 730, i) if trail[j] is not None]
                    if trail[i] is not None and win:
                        rank = sum(1 for v in win if v <= trail[i]) / len(win) * 100
                        if rank <= P:
                            e = closes[i]
                            mae = min(lows[i + k] / e - 1 for k in range(1, H + 1))
                            ret = closes[i + H] / e - 1 - 2 * 0.00075
                            for k in range(i, i + H + 1):
                                pos[k] = 1
                            trades.append({"entry_i": i, "ret": ret, "mae": mae})
                            i += H + 1
                            continue
                    i += 1
                if not trades:
                    cells.append({"L": L, "pct": P, "hold": H, "trades": 0}); continue
                worst_mae = min(t["mae"] for t in trades)
                size = 0.01 / abs(worst_mae) if worst_mae < 0 else 1.0
                net = net_strategy_returns(pos, rets)
                sr = bs.annualized_sharpe(net[L + 730:], ppy)
                bar = bs.block_bootstrap_family_bar(rets[L + 730:], [pos[L + 730:]], ppy, 20, REPS)["bar"]
                dsr = bs.deflated_sharpe_ratio(sr, net[L + 730:], ppy, 8)
                sized_total = size * sum(t["ret"] for t in trades) * 100
                cells.append({"L": L, "pct": P, "hold": H, "trades": len(trades),
                              "wins": sum(1 for t in trades if t["ret"] > 0),
                              "sum_ret_pct_notional": round(sum(t["ret"] for t in trades) * 100, 2),
                              "worst_mae_pct": round(worst_mae * 100, 2),
                              "size_frac": round(size, 3), "sized_total_pct_capital": round(sized_total, 2),
                              "sharpe": round(sr, 3), "block_bar": round(bar, 3),
                              "deflated_sharpe": round(dsr, 3),
                              "clears": sr > bar and not math.isnan(dsr) and dsr >= 0.95})
                c = cells[-1]
                print(f"  L={L} p{P} H={H}: n={c['trades']:2d} W={c['wins']:2d} "
                      f"notional {c['sum_ret_pct_notional']:+7.2f}% worstMAE {c['worst_mae_pct']}% "
                      f"sized {c['sized_total_pct_capital']:+.2f}%cap Sharpe {sr:+.2f} bar {bar:.2f} "
                      f"DSR {dsr:.3f}" + ("  <-- CLEARS" if c["clears"] else ""))

    # breadth cell
    port, ewbh, L = _breadth_reversal_returns()
    a = L + 1
    sr_b = bs.annualized_sharpe(port[a:], ppy); sr_ew = bs.annualized_sharpe(ewbh[a:], ppy)
    dd_b = _maxdd(port[a:]); dd_ew = _maxdd(ewbh[a:])
    bar_b = bs.block_bootstrap_family_bar(ewbh[a:], [[1 if port[i] != 0 else 0 for i in range(a, len(port))]],
                                          ppy, 20, REPS)["bar"] if False else None
    beats = sr_b > sr_ew and dd_b < dd_ew
    breadth = {"sharpe": round(sr_b, 3), "ew_buyhold_sharpe": round(sr_ew, 3),
               "maxdd_log": round(dd_b, 3), "ew_buyhold_maxdd_log": round(dd_ew, 3),
               "beats_ew_on_sharpe_and_maxdd": beats,
               "total_pct": round(sum(port[a:]) * 100, 2),
               "ew_total_pct": round(sum(ewbh[a:]) * 100, 2)}
    print(f"\n  breadth: Sharpe {sr_b:+.2f} (EW {sr_ew:+.2f}) maxDD {dd_b:.2f} (EW {dd_ew:.2f}) "
          f"total {breadth['total_pct']:+.1f}% (EW {breadth['ew_total_pct']:+.1f}%) "
          f"=> {'BEATS EW' if beats else 'does NOT beat EW'} on Sharpe+maxDD")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "batch5_sc.json").write_text(json.dumps(
        {"single_asset": cells, "breadth": breadth}, indent=1), encoding="utf-8")
    print("written: research/output/batch5_sc.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=("sf", "sa", "sd", "sb", "sc"))
    args = ap.parse_args()
    {"sf": phase_sf, "sa": phase_sa, "sd": phase_sd, "sb": phase_sb, "sc": phase_sc}[args.phase]()


if __name__ == "__main__":
    main()
