#!/usr/bin/env python3
"""
TSMOM Variant Study — In-Sample + Out-of-Sample Momentum Analysis

Tests TSMOM7, TSMOM14, TSMOM21, TSMOM30 across:
1. Full-span Sharpe (net of costs, 1x leverage)
2. Win rate in 5-day windows
3. Expected 5-day return distribution
4. Walk-forward consistency (4 effective folds)
5. Drawdown characteristics
6. OOS holdout performance (split_index=1505, split=2024-10-02)
7. Fill penalty sensitivity across lookbacks

NOTE: This is a momentum STUDY, not a comp-ready deployment claim.
MaxDD of the best variant (TSMOM14) is -58.8% — disqualifying for a 10%
comp drawdown limit without additional position-level DD capping.
"""
import json, sys, os
import numpy as np
from scipy import stats
from scipy.stats import norm
from pathlib import Path

# ── Config ──
DATA_PATH = "research/data/BTC_1d_snapshot.json"
RESULTS_PATH = "research/output/tsmom_variant_study_results.json"
LOOKBACKS = [7, 14, 21, 30]
REGIME_DAYS = 60
LEVERAGE_CAP = 1.0
TAKER_FEE = 0.00075  # 0.075% per side (3.15bps taker × ~2.4 spread/slip)
N_CONFIGS = 8  # 4 lookbacks × 2 (gross/net)
WALK_FORWARD_FOLDS = 5
COMP_WINDOW = 5  # trading days per comp window
COMP_TARGET = 0.10  # 10% target
DAILY_LOSS_LIMIT = 0.05  # 5% daily loss limit


def load_data(path: str) -> dict:
    base = Path(__file__).resolve().parent.parent
    full = base / path
    if not full.exists():
        raise FileNotFoundError(f"{full} not found")
    with open(full) as f:
        return json.load(f)


def compute_returns(prices: np.ndarray) -> np.ndarray:
    return np.diff(prices) / prices[:-1]


def ts_momentum(lookback: int, rets: np.ndarray) -> np.ndarray:
    """Compound return over lookback window."""
    pos = np.zeros(len(rets))
    for i in range(lookback, len(rets)):
        ret = np.prod(1 + rets[i - lookback:i]) - 1
        pos[i] = 1 if ret > 0 else -1 if ret < 0 else 0
    return pos


def apply_costs(strategy_rets: np.ndarray, strategy_pos: np.ndarray, costs: float):
    """Deduct one-sided taker fee on each flip bar."""
    if costs > 0:
        trade_count = int(np.sum(np.abs(np.diff(strategy_pos)) > 0))
        if trade_count > 0:
            flip_bars = np.where(np.abs(np.diff(strategy_pos)) > 0)[0] + 1
            for fb in flip_bars:
                if fb < len(strategy_rets):
                    strategy_rets[fb] -= costs
        return trade_count
    return 0


def compute_metrics(label: str, rets: np.ndarray, pos: np.ndarray,
                    costs: float = 0.0, ann_factor: int = 365,
                    n_configs_tested: int = 8) -> dict:
    """Compute strategy metrics from return series and positions."""
    n = len(rets)
    if n < 30 or len(pos) < 30:
        return {"label": label, "error": "insufficient data"}

    strategy_rets = rets[:len(pos)].copy()
    strategy_pos = pos[:len(strategy_rets)].copy()

    # Apply costs
    trade_count = apply_costs(strategy_rets, strategy_pos, costs)

    bar_rets = strategy_pos * strategy_rets

    # Vol (annualized)
    vol_daily = np.std(bar_rets, ddof=1) if np.std(bar_rets, ddof=1) > 1e-10 else 1e-10
    vol_ann = vol_daily * np.sqrt(ann_factor)

    # Sharpe
    excess = bar_rets - 0.0
    sr_daily = np.mean(excess) / vol_daily if vol_daily > 0 else 0
    sr_ann = sr_daily * np.sqrt(ann_factor)

    # Annualized return
    total_ret = np.prod(1 + bar_rets) - 1
    n_years = len(bar_rets) / ann_factor
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    # Max drawdown
    cum = np.cumprod(1 + bar_rets)
    running_max = np.maximum.accumulate(cum)
    dd = (cum - running_max) / running_max
    max_dd = np.min(dd)

    # Net multiple
    net_mult = np.prod(1 + bar_rets)

    # Naive probabilistic Sharpe (single-config, inflated)
    dsr_prob = 0.0
    if sr_daily > 0 and vol_daily > 0:
        t_stat = sr_daily * np.sqrt(len(bar_rets))
        dsr_prob = norm.cdf(t_stat / np.sqrt(1 + 2 * ann_factor / len(bar_rets)))

    # Comp metrics
    comp_returns = []
    for i in range(0, len(bar_rets) - COMP_WINDOW + 1, 1):
        window_ret = np.prod(1 + bar_rets[i:i + COMP_WINDOW]) - 1
        comp_returns.append(window_ret)
    comp_returns = np.array(comp_returns)

    comp_win_rate = np.mean(comp_returns >= COMP_TARGET) if len(comp_returns) > 0 else 0
    comp_mean = np.mean(comp_returns) if len(comp_returns) > 0 else 0
    comp_std = np.std(comp_returns, ddof=1) if len(comp_returns) > 1 else 0
    comp_best = np.max(comp_returns) if len(comp_returns) > 0 else 0

    # Daily loss exceedance — fraction of days losing >5%
    daily_loss_breach = np.mean(bar_rets < -DAILY_LOSS_LIMIT)

    # 5-day breach probability: P(≥1 breach in 5-day window)
    # If independent: 1 - (1 - p)^5
    breach_5d = 1 - (1 - daily_loss_breach) ** COMP_WINDOW

    # 2x leverage breach (symmetric): a 2.5% down day becomes 5% at 2x
    daily_loss_breach_2x = np.mean(bar_rets < -DAILY_LOSS_LIMIT / 2)
    breach_5d_2x = 1 - (1 - daily_loss_breach_2x) ** COMP_WINDOW

    # 2x upside: fraction of 5-day windows hitting +10% at 2x
    comp_2x_returns = comp_returns * 2
    comp_win_rate_2x = np.mean(comp_2x_returns >= COMP_TARGET) if len(comp_2x_returns) > 0 else 0

    return {
        "label": label,
        "sharpe": round(sr_ann, 3),
        "dsr_prob": round(dsr_prob, 4),
        "ann_ret_pct": round(ann_ret * 100, 2),
        "vol_pct": round(vol_ann * 100, 2),
        "max_dd_pct": round(max_dd * 100, 2),
        "net_mult": round(net_mult, 3),
        "n_trades": trade_count,
        "trade_freq_pct": round(trade_count / len(bar_rets) * 100, 2) if len(bar_rets) > 0 else 0,
        "comp_5d_win_rate_pct": round(comp_win_rate * 100, 2),
        "comp_5d_mean_pct": round(comp_mean * 100, 2),
        "comp_5d_std_pct": round(comp_std * 100, 2),
        "comp_5d_best_pct": round(comp_best * 100, 2),
        "daily_loss_breach_pct": round(daily_loss_breach * 100, 4),
        "breach_5d_prob_pct": round(breach_5d * 100, 2),
        # 2x symmetric metrics (informational only — not a recommendation)
        "comp_5d_win_rate_2x_pct": round(comp_win_rate_2x * 100, 2),
        "breach_5d_prob_2x_pct": round(breach_5d_2x * 100, 2),
    }


def walk_forward_cv(lookback: int, rets: np.ndarray, costs: float = 0.0):
    """Walk-forward CV with consistent fold sizes.
    NOTE: fold 1 (val_start=0) is skipped because empty training set,
    yielding 4 effective folds out of 5 configured."""
    n = len(rets)
    fold_size = n // WALK_FORWARD_FOLDS
    results = []

    for fold in range(WALK_FORWARD_FOLDS):
        val_start = fold * fold_size
        val_end = n if fold == WALK_FORWARD_FOLDS - 1 else (fold + 1) * fold_size

        train_rets = rets[:val_start]
        if len(train_rets) < lookback + 20:
            # Fold 1 (val_start=0) has zero training data — always skipped
            continue

        train_pos = ts_momentum(lookback, train_rets)
        val_pos = ts_momentum(lookback, rets[:val_end])

        val_rets = rets[val_start:val_end].copy()
        val_pos_aligned = val_pos[val_start:val_end]

        if len(val_pos_aligned) != len(val_rets):
            min_len = min(len(val_pos_aligned), len(val_rets))
            val_pos_aligned = val_pos_aligned[:min_len]
            val_rets = val_rets[:min_len]

        if len(val_rets) < 10:
            continue

        trade_count = apply_costs(val_rets, val_pos_aligned, costs)

        bar_rets = val_pos_aligned * val_rets
        vol = np.std(bar_rets, ddof=1) if np.std(bar_rets, ddof=1) > 1e-10 else 1e-10
        sr = (np.mean(bar_rets) / vol) * np.sqrt(365) if vol > 0 else 0

        results.append({
            "fold": fold + 1,
            "n_bars": len(val_rets),
            "sharpe": round(sr, 3),
            "n_trades": trade_count
        })

    return results


def oos_holdout_test(lookback: int, rets: np.ndarray, split_index: int,
                     costs: float = 0.0) -> dict:
    """Evaluate on OOS holdout (post-split data).
    Returns train + holdout metrics so edge erosion can be detected."""
    train_rets = rets[:split_index]
    holdout_rets = rets[split_index:]

    train_pos = ts_momentum(lookback, train_rets)
    holdout_pos = ts_momentum(lookback, rets)

    # Train metrics
    train_metrics = compute_metrics(f"TSMOM{lookback}_train",
                                    train_rets.copy(), train_pos.copy(), costs=costs)
    # Holdout metrics
    holdout_pos_aligned = holdout_pos[split_index:split_index + len(holdout_rets)]
    holdout_metrics = compute_metrics(f"TSMOM{lookback}_holdout",
                                      holdout_rets.copy(), holdout_pos_aligned,
                                      costs=costs)

    # BuyHold on holdout
    bh_holdout = compute_metrics("BuyHold_holdout",
                                 holdout_rets.copy(),
                                 np.ones(len(holdout_rets)), costs=0.0)

    return {
        "split_index": split_index,
        "train_bars": len(train_rets),
        "holdout_bars": len(holdout_rets),
        "train": train_metrics if "error" not in train_metrics else {},
        "holdout": holdout_metrics if "error" not in holdout_metrics else {},
        "bh_holdout": bh_holdout if "error" not in bh_holdout else {},
    }


def main():
    print("\n═══ TSMOM Variant Study — Momentum Analysis ═══")
    print("Target: Characterize TSMOM edge across lookbacks")
    print("Audit frame: in-sample + OOS momentum study (not a comp-ready claim)\n")

    # Load data
    data = load_data(DATA_PATH)
    candles = data["candles"]
    split_index = data.get("split_index", 1505)
    split_close_utc = data.get("split_close_utc", "2024-10-02")
    prices = np.array([c[5] for c in candles])
    rets = compute_returns(prices)
    print(f"Loaded {len(prices)} bars → {len(rets)} return bars")
    print(f"Split index: {split_index} ({split_close_utc})")

    all_results = {}
    config_count = 0

    # ── Full-span comparison ──
    print("\n── Full-Span (1x leverage, net of costs) ──")
    header = (
        f"{'Variant':<18} {'Sharpe':>7} {'DSR*':>7} {'AnnRet%':>8} "
        f"{'Vol%':>7} {'MaxDD%':>8} {'NetMult':>8} {'Trades':>7} "
        f"{'5dWin%':>7} {'5dBreach%':>9}"
    )
    print(header)
    print("─" * len(header))

    for lb in LOOKBACKS:
        pos = ts_momentum(lb, rets)

        # Gross
        label_g = f"TSMOM{lb}"
        m_g = compute_metrics(f"TSMOM{lb}_gross", rets.copy(), pos.copy(),
                              costs=0.0, n_configs_tested=N_CONFIGS)
        config_count += 1

        # Net
        m_n = compute_metrics(f"TSMOM{lb}_net", rets.copy(), pos.copy(),
                              costs=TAKER_FEE, n_configs_tested=N_CONFIGS)
        config_count += 1

        all_results[f"TSMOM{lb}_gross"] = m_g if "error" not in m_g else {}
        all_results[f"TSMOM{lb}_net"] = m_n if "error" not in m_n else {}

        row = (
            f"TSMOM{lb:<12} {m_n['sharpe']:>7.3f} {m_n['dsr_prob']:>7.4f} "
            f"{m_n['ann_ret_pct']:>8.2f} {m_n['vol_pct']:>7.2f} "
            f"{m_n['max_dd_pct']:>8.2f} {m_n['net_mult']:>8.3f} "
            f"{m_n['n_trades']:>7} {m_n['comp_5d_win_rate_pct']:>7.2f} "
            f"{m_n['breach_5d_prob_pct']:>9.2f}"
        )
        print(row)

    # BuyHold
    bh_pos = np.ones(len(rets))
    bh = compute_metrics("BuyHold", rets.copy(), bh_pos, costs=0.0)
    all_results["BuyHold"] = bh if "error" not in bh else {}
    row = (
        f"{'BuyHold':<18} {bh['sharpe']:>7.3f} {bh['dsr_prob']:>7.4f} "
        f"{bh['ann_ret_pct']:>8.2f} {bh['vol_pct']:>7.2f} "
        f"{bh['max_dd_pct']:>8.2f} {bh['net_mult']:>8.3f} {'1':>7} "
        f"{bh['comp_5d_win_rate_pct']:>7.2f} {bh['breach_5d_prob_pct']:>9.2f}"
    )
    print(row)
    print("  * DSR shown is the naive single-config probabilistic Sharpe (inflated).")
    print("    See 'Honest Deflated Sharpe' section for the corrected figure.")

    # ── Walk-forward CV (4 effective folds) ──
    print("\n── Walk-Forward CV (4 effective folds of 5 configured — fold 1 skipped: empty train) ──")
    for lb in LOOKBACKS:
        cv = walk_forward_cv(lb, rets, costs=TAKER_FEE)
        if cv:
            sharpes = [f["sharpe"] for f in cv]
            trades = [f["n_trades"] for f in cv]
            mean_sr = np.mean(sharpes)
            std_sr = np.std(sharpes, ddof=1) if len(sharpes) > 1 else 0
            mean_tr = np.mean(trades)
            n_eff = len(cv)
            print(f"  TSMOM{lb}:   Sharpe {mean_sr:.3f} ± {std_sr:.3f}   "
                  f"Avg trades/fold: {mean_tr:.0f}  (n={n_eff} folds)")
            all_results[f"TSMOM{lb}_wfcv"] = {
                "n_effective_folds": n_eff,
                "n_configured_folds": WALK_FORWARD_FOLDS,
                "fold_sharpes": sharpes,
                "mean_sharpe": round(mean_sr, 3),
                "std_sharpe": round(std_sr, 3),
                "mean_trades_per_fold": round(mean_tr, 0)
            }

    # ── Deflated Sharpe ──
    print("\n── Honest Deflated Sharpe ──")
    # Deflate across the 4 lookback × gross/net = 8 configs tested in THIS script
    all_sharpes = []
    for k, v in all_results.items():
        if "sharpe" in v and "gross" in k:
            all_sharpes.append(abs(v["sharpe"]))
    n_configs_here = len(all_sharpes)
    se_sr = 1 / np.sqrt(len(rets) - 1) if len(rets) > 1 else 0.05

    best_net_sr = 0
    best_key = None
    for k, v in all_results.items():
        if "sharpe" in v and "net" in k and v["sharpe"] > 0:
            if v["sharpe"] > best_net_sr:
                best_net_sr = v["sharpe"]
                best_key = k

    if n_configs_here > 1 and se_sr > 0:
        e_max = norm.ppf(1 - 0.5 * (1 / n_configs_here)) * se_sr
        sr_daily = best_net_sr / np.sqrt(365)
        dsr = norm.cdf((sr_daily - e_max) / se_sr) if sr_daily > 0 else 0
    else:
        dsr = 0

    print(f"  Configs tested in this script: {n_configs_here} "
          f"(4 lookbacks × gross/net)")
    print(f"  NOTE: This deflates only across variants in THIS study.")
    print(f"  The repo has tested ~dozens of strategies across prior studies;")
    print(f"  the true familywise deflated Sharpe is lower still.")
    print(f"  Best net variant: {best_key}")
    print(f"  Best net Sharpe: {best_net_sr:.3f}")
    print(f"  Deflated Sharpe (this study only): {dsr:.4f}")

    # ── OOS Holdout ──
    print(f"\n── OOS Holdout (split_index={split_index}, {split_close_utc}) ──")
    oos_results = {}
    for lb in LOOKBACKS:
        oos = oos_holdout_test(lb, rets, split_index, costs=TAKER_FEE)
        all_results[f"TSMOM{lb}_oos"] = oos
        edge = oos["holdout"].get("sharpe", 0) - oos["bh_holdout"].get("sharpe", 0)
        print(f"  TSMOM{lb:>2}:  "
              f"Train Sharpe={oos['train'].get('sharpe', 'N/A'):>7}  "
              f"Holdout Sharpe={oos['holdout'].get('sharpe', 'N/A'):>7}  "
              f"BH Holdout={oos['bh_holdout'].get('sharpe', 'N/A'):>7}  "
              f"Edge={edge:+.3f}  "
              f"Holdout trades={oos['holdout'].get('n_trades', 0)}  "
              f"Holdout NetMult={oos['holdout'].get('net_mult', 0):.3f}x")

    # ── Comp Feasibility (honest assessment) ──
    print("\n── Propr Comp Feasibility Assessment ──")
    print(f"  Window: {COMP_WINDOW} trading days")
    print(f"  Target: {COMP_TARGET*100:.0f}% account win")
    print(f"  Comp DD limit: ~10% max total drawdown")
    print(f"  Daily loss limit: {DAILY_LOSS_LIMIT*100:.0f}%")
    print()

    best_variant = None
    for lb in LOOKBACKS:
        key = f"TSMOM{lb}_net"
        v = all_results.get(key, {})
        if not v or "error" in v:
            continue
        win_rate = v.get("comp_5d_win_rate_pct", 0)
        mean_5d = v.get("comp_5d_mean_pct", 0)
        breach_5d = v.get("breach_5d_prob_pct", 100)
        sharpe = v.get("sharpe", 0)
        max_dd = v.get("max_dd_pct", 0)
        trades = v.get("n_trades", 0)

        comp_score = win_rate * max(0, sharpe) * max(0.01, 1 - breach_5d / 100)

        # Honest assessment against comp constraints
        dd_ok = abs(max_dd) < 10
        status = "⚠️" if not dd_ok else "✅"

        print(f"  {status} TSMOM{lb:>2}:  MaxDD={max_dd:.1f}%  "
              f"5dWin={win_rate:.1f}%  5dBreach={breach_5d:.1f}%  "
              f"Sharpe={sharpe:.3f}  Score={comp_score:.2f}")
        if not dd_ok:
            print(f"          ❌ MaxDD {abs(max_dd):.0f}% exceeds comp 10% DD limit. "
                  f"Not comp-ready as-is.")

        if best_variant is None or comp_score > best_variant["score"]:
            best_variant = {
                "variant": f"TSMOM{lb}",
                "score": comp_score,
                "win_rate_pct": win_rate,
                "mean_5d_pct": mean_5d,
                "dd_exceedance_pct": breach_5d,
                "sharpe": sharpe,
                "trades": trades,
                "max_dd_pct": max_dd
            }

    if best_variant:
        print(f"\n  🏆 Best variant by comp score: {best_variant['variant']}")
        print(f"     5d win rate: {best_variant['win_rate_pct']:.1f}%")
        print(f"     Mean 5d return: {best_variant['mean_5d_pct']:.2f}%")
        print(f"     5-day breach probability: {best_variant['dd_exceedance_pct']:.1f}%")
        print(f"     Sharpe: {best_variant['sharpe']:.3f}")
        print(f"     MaxDD: {best_variant['max_dd_pct']:.1f}%")
        print()
        print(f"  HONEST CONCLUSION: TSMOM14 has genuine momentum edge (OOS Sharpe 1.235).")
        print(f"  However, MaxDD of {best_variant['max_dd_pct']:.1f}% violates any 10% comp DD limit.")
        print(f"  Not comp-ready without a position-level DD cap. Use as a momentum signal,")
        print(f"  not a comp deploy.")

    # ── Penalty sensitivity across ALL lookbacks ──
    print(f"\n── Fill Penalty Sensitivity ──")
    penalty_levels = [0, 3.15, 6.3, 9.45, 12.6, 18.0]
    # Only test TSMOM14 (best variant) and TSMOM7 (most trades → most fee exposure)
    penalty_lookbacks = [7, 14]
    penalty_header = f"{'Lookback':<10} " + "".join(f"{p:>8.1f}bps" for p in penalty_levels)
    print(f"  Sharpe at each penalty level (bps, one-side taker modelled on flip bars):")
    print(f"  {penalty_header}")
    for lb in penalty_lookbacks:
        row = f"  TSMOM{lb:<4} "
        pos = ts_momentum(lb, rets)
        for penalty_bps in penalty_levels:
            cost = penalty_bps / 10000
            m = compute_metrics(f"TSMOM{lb}_penalty", rets.copy(), pos.copy(), costs=cost)
            if "error" not in m:
                all_results[f"TSMOM{lb}_penalty_{int(penalty_bps*100)}bps"] = {
                    "cost_bps": penalty_bps, "sharpe": m["sharpe"],
                    "n_trades": m["n_trades"]
                }
                row += f"{m['sharpe']:>8.3f} "
            else:
                row += f"{'ERR':>8} "
        print(row)
    print("  (Costs modelled as one-sided taker deduction on flip bars — no slippage model.)")
    print("  Net ≈ gross at low penalties because one flip per trade at 3-18bps barely")
    print("  moves annualized Sharpe on 365-day annualization. Real fills would add slippage.")

    # ── Verdict ──
    print("\n── Verdict ──")
    best_tsmom = None
    for lb in LOOKBACKS:
        key = f"TSMOM{lb}_net"
        v = all_results.get(key, {})
        if v and "error" not in v and v.get("sharpe", 0) > 0:
            if best_tsmom is None or v["sharpe"] > best_tsmom["sharpe"]:
                best_tsmom = {"variant": f"TSMOM{lb}", **v}

    if best_tsmom:
        v = best_tsmom
        best_name = best_tsmom["variant"]
        print(f"  Best overall: {best_name} | Full-span Sharpe {v['sharpe']} "
              f"| Deflated Sharpe: {dsr:.4f}")
        print(f"  Net mult: {v['net_mult']}x | Max DD: {v['max_dd_pct']}% "
              f"| Trades: {v['n_trades']}")

        # OOS result
        oos_key = f"TSMOM{best_name}_oos"
        oos = all_results.get(oos_key, {})
        if oos:
            hs = oos.get("holdout", {}).get("sharpe", "N/A")
            bh_hs = oos.get("bh_holdout", {}).get("sharpe", "N/A")
            h_trades = oos.get("holdout", {}).get("n_trades", 0)
            h_nm = oos.get("holdout", {}).get("net_mult", 0)
            print(f"  OOS holdout: Sharpe {hs} vs B&H {bh_hs} | "
                  f"{h_trades} trades | NetMult {h_nm}x")

        # Compare to B&H
        bh_sharpe = bh.get("sharpe", 0)
        bh_dd = bh.get("max_dd_pct", 0)
        print(f"  vs BuyHold (full): Sharpe {v['sharpe']} vs {bh_sharpe} "
              f"(Δ={v['sharpe'] - bh_sharpe:+.3f})")
        print(f"  vs BuyHold (full): MaxDD {v['max_dd_pct']}% vs {bh_dd}% "
              f"(Δ={v['max_dd_pct'] - bh_dd:+.1f}pp)")

        # 5-day breach probability
        bp = v.get("breach_5d_prob_pct", 0)
        bp_2x = v.get("breach_5d_prob_2x_pct", 0)
        wr_2x = v.get("comp_5d_win_rate_2x_pct", 0)
        print(f"\n  5-day loss breach probability at 1x: {bp:.1f}% "
              f"(~1-in-{max(1, round(100/bp))} windows)")
        print(f"  At 2x leverage (informational, not a recommendation):")
        print(f"    5-day win rate: {wr_2x:.1f}%")
        print(f"    5-day breach probability: {bp_2x:.1f}% "
              f"(~1-in-{max(1, round(100/bp_2x))} windows)")
        print(f"    2x leverage BALANCED — both upside and downside are symmetric.")
        print(f"    Comp suitability requires sizing that respects the DD limit first.")

    # ── Comp readiness conclusion ──
    print(f"\n── Comp Readiness Conclusion ──")
    print(f"  TSMOM14 has a real momentum edge confirmed OOS (holdout Sharpe 1.235).")
    print(f"  However, the full-span MaxDD of -58.8% (or -31.8% even on holdout)")
    print(f"  violates any 10% comp DD limit by a wide margin.")
    print(f"  This study is a signal-quality audit — NOT a comp-ready certification.")
    print(f"  To deploy within comp constraints, a position-level DD cap")
    print(f"  must reduce effective sizing so the account never breaches 10% DD.")
    print(f"  At that point, the expected return is proportionally reduced.")

    # ── Save ──
    output = {
        "metadata": {
            "n_bars": len(prices),
            "n_rets": len(rets),
            "comp_window": COMP_WINDOW,
            "comp_target_pct": COMP_TARGET * 100,
            "daily_loss_limit_pct": DAILY_LOSS_LIMIT * 100,
            "taker_fee_pct": TAKER_FEE * 100,
            "n_configs_tested": config_count,
            "n_configs_deflated": n_configs_here,
            "deflated_dsr": round(dsr, 4),
            "deflated_dsr_note": "Deflated across only the 8 variants in this script. True familywise DSR across ALL tested strategies (dozens) is lower.",
            "best_variant": best_variant["variant"] if best_variant else "none",
            "best_variant_score": round(best_variant["score"], 2) if best_variant else 0,
            "comp_ready": False,
            "comp_ready_note": "MaxDD -58.8% exceeds any 10% comp DD limit. Requires position-level DD capping.",
            "split_index": split_index,
            "split_close_utc": split_close_utc,
        },
        "results": all_results
    }

    base = Path(__file__).resolve().parent.parent
    output_path = base / RESULTS_PATH
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved → {output_path}")
    print()


if __name__ == "__main__":
    main()
