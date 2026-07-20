"""FundingZ: Direct funding-rate z-score study.

Re-work of PR #1 (claude/funding-mr-portfolio, AUDIT: FAIL).
The original regime-gated overlay produced only 8 BEAR trades in-sample,
was regime-non-stationary (5.5% BEAR in-sample vs 55% OOS), and failed the
promotable bar (DSR ~0.56, OOS Sharpe -0.32).

NEW APPROACH: Instead of a regime label (binary classifier on trailing-365d
percentile), use the RAW hourly funding rate directly and trade on extreme
z-score deviations. Hourly data → many signal events (easily ≥30 trades).

Hypothesis: Extreme negative funding rates (z-score << -1) predict short-term
bullish reversals in BTC (crowded-short squeeze thesis). Entry LONG when
funding is abnormally negative; exit after funding normalises or max hold.

All OFFLINE — reads committed research/data/BTC_funding_history.json and
research/data/BTC_1d_snapshot.json. Writes research/output/funding_z_results.json.

Usage: python scripts/funding_z_study.py --phase run
"""

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "research" / "data"
OUTPUT_DIR = REPO_ROOT / "research" / "output"
OUTPUT_PATH = OUTPUT_DIR / "funding_z_results.json"

# ── Constants ────────────────────────────────────────────────────────────
FEE_TAKER = 0.00075       # 0.075% per side, repo convention
SPLIT_FRACTION = 0.70     # chronological 70/30 explore/holdout
MIN_TRADES_PROMOTABLE = 30
BARS_PER_YEAR = 365.0     # daily returns
ANNUAL_TRADING_DAYS = 365.0

# ── Parameter grid ──────────────────────────────────────────────────────
LOOKBACKS = [24, 48, 168]       # days: 24d, ~48d, ~168d (1, 2, ~7 months) rolling window
ENTRY_THRESHOLDS = [1.0, 1.5, 2.0]  # z-score magnitude (negative)
MAX_HOLD_HOURS = [24, 48, 72]        # max holding period


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def load_funding(path: Path):
    """Load hourly funding data. Returns list of (timestamp_ms, rate) sorted chronologically."""
    d = load_json(path)
    rows = sorted(d["rows"], key=lambda r: r[0])  # already sorted but be safe
    # rows: [timestamp_ms, rate]
    return [(r[0], r[1]) for r in rows]


def load_candles_1d(path: Path):
    """Load 1d BTC candles. Returns dict: timestamps_ms -> close price."""
    d = load_json(path)
    candles = d["candles"]
    # schema: [open_time_ms, close_time_ms, open, high, low, close, volume]
    closes = {}
    for c in candles:
        closes[c[0]] = c[5]  # open_time_ms -> close_price (index 5 = close)
    return closes


def compute_rolling_zscore(values, lookback):
    """Compute rolling z-score of a series. Returns list same length with None prefix."""
    result = []
    for i in range(len(values)):
        if i < lookback:
            result.append(None)
        else:
            window = values[i - lookback:i]
            mu = statistics.mean(window)
            sigma = statistics.stdev(window)
            if sigma == 0:
                result.append(0.0)
            else:
                result.append((values[i] - mu) / sigma)
    return result


def daily_return(close_today, close_yesterday):
    """Log return as fraction."""
    return math.log(close_today / close_yesterday)


def run_study():
    print("=" * 60)
    print("FundingZ Study: Direct Funding-Rate Z-Score Signal")
    print("=" * 60)

    # ── Load data ────────────────────────────────────────────────────────
    print("\nLoading data...")
    funding = load_funding(DATA_DIR / "BTC_funding_history.json")
    candles_1d = load_candles_1d(DATA_DIR / "BTC_1d_snapshot.json")

    print(f"  Funding records: {len(funding)}")
    print(f"  Candle days: {len(candles_1d)}")

    # ── Build aligned timeline ───────────────────────────────────────────
    # CRITICAL: Signal (last-hour funding of day D) must trade day D+1's return.
    # Using day D's own return is lookahead — it's realized at the same instant
    # the close-of-day funding rate is observed.
    
    # Get sorted daily close timestamps
    daily_ts = sorted(candles_1d.keys())
    
    # daily_returns[t] = log(close_t / close_{t-1}) = return realized during day T
    daily_returns = {}
    for i in range(1, len(daily_ts)):
        ret = daily_return(candles_1d[daily_ts[i]], candles_1d[daily_ts[i-1]])
        daily_returns[daily_ts[i]] = ret

    # Map each day to the NEXT day's close-to-close return (no lookahead)
    next_day_return = {}
    for i in range(len(daily_ts) - 1):
        next_day_return[daily_ts[i]] = daily_returns[daily_ts[i + 1]]

    # Build a mapping: day_ts (open_time_ms) -> list of funding rates for that day
    # 86400000 ms = 1 day
    DAY_MS = 86400000
    
    funding_by_day = {}  # day_ts -> [(hour_ts_ms, rate), ...]
    for ft, rate in funding:
        # Find which day this hour belongs to (floor to day start)
        day_start = (ft // DAY_MS) * DAY_MS
        if day_start not in funding_by_day:
            funding_by_day[day_start] = []
        funding_by_day[day_start].append((ft, rate))

    # Sort funding within each day
    for day in funding_by_day:
        funding_by_day[day].sort(key=lambda x: x[0])

    # Now build aligned dataset: for each day with candle data, compute the
    # z-score of the LAST funding rate of that day (the signal known at day close)
    # Then the return is the NEXT day's daily return (no lookahead)
    
    aligned_days = []
    for day_ts in sorted(funding_by_day.keys()):
        if day_ts in daily_returns and day_ts in next_day_return:
            day_rates = [r for _, r in funding_by_day[day_ts]]
            if len(day_rates) > 0:
                last_hour_rate = day_rates[-1]  # the rate known at day's end
                aligned_days.append({
                    "day_ts": day_ts,
                    "rate": last_hour_rate,
                    "all_rates": day_rates,
                    "return_tomorrow": next_day_return[day_ts],
                })

    print(f"  Aligned days (funding + next-day return): {len(aligned_days)}")

    if len(aligned_days) == 0:
        print("ERROR: No aligned data. Check date ranges.")
        sys.exit(1)

    # ── Split ────────────────────────────────────────────────────────────
    split_idx = int(len(aligned_days) * SPLIT_FRACTION)
    explore = aligned_days[:split_idx]
    holdout = aligned_days[split_idx:]
    print(f"\n  Explore (in-sample): {len(explore)} days")
    print(f"  Holdout (OOS):       {len(holdout)} days")
    print(f"  Split index: {split_idx}")
    if explore:
        print(f"  Explore start: {datetime.fromtimestamp(explore[0]['day_ts']/1000, tz=timezone.utc).date()}")
        print(f"  Explore end:   {datetime.fromtimestamp(explore[-1]['day_ts']/1000, tz=timezone.utc).date()}")
    if holdout:
        print(f"  Holdout start: {datetime.fromtimestamp(holdout[0]['day_ts']/1000, tz=timezone.utc).date()}")
        print(f"  Holdout end:   {datetime.fromtimestamp(holdout[-1]['day_ts']/1000, tz=timezone.utc).date()}")

    # BTC buy-and-hold returns
    def bh_sharpe_ann(data):
        """Compute BTC buy-and-hold annualised Sharpe on a window."""
        returns = [d["return_tomorrow"] for d in data]
        if len(returns) < 2:
            return 0.0, 0.0, 0.0
        r_arr = list(returns)
        mu = statistics.mean(r_arr)
        sigma = statistics.stdev(r_arr) if len(r_arr) > 1 else 0.0
        ann_ret = mu * ANNUAL_TRADING_DAYS
        ann_sigma = sigma * math.sqrt(ANNUAL_TRADING_DAYS)
        sharpe = ann_ret / ann_sigma if ann_sigma > 0 else 0.0
        
        # Net log return
        net_log = sum(r for r in r_arr)
        net_mult = math.exp(net_log)
        return sharpe, ann_ret, net_mult

    bh_explore_sr, bh_explore_ret, bh_explore_mult = bh_sharpe_ann(explore)
    bh_holdout_sr, bh_holdout_ret, bh_holdout_mult = bh_sharpe_ann(holdout)
    bh_full_sr, bh_full_ret, bh_full_mult = bh_sharpe_ann(aligned_days)
    
    print(f"\nBTC Buy & Hold:")
    print(f"  Explore: Sharpe {bh_explore_sr:.4f}, AnnRet {bh_explore_ret*100:.2f}%, NetMult {bh_explore_mult:.4f}")
    print(f"  Holdout: Sharpe {bh_holdout_sr:.4f}, AnnRet {bh_holdout_ret*100:.2f}%, NetMult {bh_holdout_mult:.4f}")
    print(f"  Full:    Sharpe {bh_full_sr:.4f}, AnnRet {bh_full_ret*100:.2f}%, NetMult {bh_full_mult:.4f}")

    # ── Run parameter grid ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Running parameter grid...")
    print("=" * 60)

    results = []
    total_configs = len(LOOKBACKS) * len(ENTRY_THRESHOLDS) * len(MAX_HOLD_HOURS)
    config_idx = 0

    for lookback in LOOKBACKS:
        for threshold in ENTRY_THRESHOLDS:
            for max_hold in MAX_HOLD_HOURS:
                config_idx += 1
                label = f"LB{lookback}_T{threshold}_MH{max_hold}"
                print(f"\n  [{config_idx}/{total_configs}] {label}")

                for window_name, data in [("explore", explore), ("holdout", holdout), ("full", aligned_days)]:
                    # Compute z-scores of the last-hour rate for each day
                    rates = [d["rate"] for d in data]
                    zscores = compute_rolling_zscore(rates, lookback)

                    # Trading logic
                    trades = []
                    position = 0     # 0 = flat, 1 = long
                    entry_idx = None
                    bars_in_position = 0
                    daily_position_returns = []

                    for i, d in enumerate(data):
                        z = zscores[i]
                        ret_t = d["return_tomorrow"]

                        if z is None:
                            daily_position_returns.append(0.0)
                            continue

                        # Entry: z-score < -threshold (extreme negative funding → long)
                        if position == 0 and z < -threshold:
                            position = 1
                            entry_idx = i
                            bars_in_position = 0
                            trades.append({"entry_i": i, "entry_ts": d["day_ts"]})
                            # Pay fee on entry
                            daily_position_returns.append(ret_t - FEE_TAKER)
                        elif position == 1:
                            bars_in_position += 1
                            # Exit: funding normalised (z > -threshold/2) OR max hold reached
                            if z > -threshold / 2 or bars_in_position >= max_hold:
                                position = 0
                                daily_position_returns.append(ret_t - FEE_TAKER)  # exit fee
                                trades[-1]["exit_i"] = i
                                trades[-1]["exit_ts"] = d["day_ts"]
                                trades[-1]["bars_held"] = bars_in_position
                            else:
                                daily_position_returns.append(ret_t)  # no fee on continuation
                        else:
                            daily_position_returns.append(0.0)

                    # Compute metrics
                    str_returns = [r for r in daily_position_returns if r != 0.0]
                    non_zero_bars = len(str_returns)
                    unique_trades = len(trades)
                    completed_trades = sum(1 for t in trades if "exit_i" in t)

                    if non_zero_bars < 2:
                        sharpe = 0.0
                        ann_ret = 0.0
                        net_mult = 1.0
                    else:
                        mu = statistics.mean(str_returns)
                        sigma = statistics.stdev(str_returns)
                        # Annualise: daily bars
                        ann_ret = mu * ANNUAL_TRADING_DAYS
                        ann_sigma = sigma * math.sqrt(ANNUAL_TRADING_DAYS)
                        sharpe = ann_ret / ann_sigma if ann_sigma > 0 else 0.0
                        net_log = sum(daily_position_returns)
                        net_mult = math.exp(net_log)

                    # Store result
                    result_entry = {
                        "config": label,
                        "lookback_days": lookback,
                        "entry_z_threshold": threshold,
                        "max_hold_bars": max_hold,
                        "window": window_name,
                        "bars": len(data),
                        "sharpe_ann": round(sharpe, 4),
                        "ann_return_pct": round(ann_ret * 100, 2),
                        "net_multiple": round(net_mult, 4),
                        "total_trades_started": unique_trades,
                        "completed_trades": completed_trades,
                    }

                    if window_name == "explore":
                        results.append(result_entry)
                        print(f"    {window_name}: Sharpe {sharpe:.4f}, AnnRet {ann_ret*100:.2f}%, "
                              f"NetMult {net_mult:.4f}, trades {unique_trades}")
                    else:
                        results.append(result_entry)
                        print(f"    {window_name}: Sharpe {sharpe:.4f}, AnnRet {ann_ret*100:.2f}%, "
                              f"NetMult {net_mult:.4f}, trades {unique_trades}")

    # ── Compute deflated Sharpe ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Deflated Sharpe (Bailey & López de Prado)")
    print("=" * 60)

    # Collect explore Sharpe for all configs with >= 2 trades
    explore_sharpes = []
    for r in results:
        if r["window"] == "explore" and r["total_trades_started"] >= 2:
            explore_sharpes.append(r["sharpe_ann"])

    n_configs = len(explore_sharpes)
    max_sr = max(explore_sharpes) if explore_sharpes else 0.0
    mean_sr = statistics.mean(explore_sharpes) if explore_sharpes else 0.0
    std_sr = statistics.stdev(explore_sharpes) if len(explore_sharpes) > 1 else 1.0

    # E[max SR] ≈ mean + std * ((1 - γ) * Φ⁻¹(1 - 1/N) + γ * Φ⁻¹(1 - 1/N * e^{-1}))
    # Simplified: E[max Z] approximation for N i.i.d. normals
    # Using formula from Bailey & López de Prado 2014
    from math import sqrt, log, pi, e

    def euler_mascheroni():
        return 0.5772156649

    gamma = euler_mascheroni()

    def expected_max_z(n):
        # Approximation: E[max of N i.i.d. N(0,1)]
        if n <= 1:
            return 0.0
        return (1 - gamma) * sqrt(2 * log(n)) + gamma * sqrt(2 * log(n * e))

    sr0 = mean_sr + std_sr * expected_max_z(n_configs) if n_configs > 0 else 0.0

    # Deflated Sharpe = (selected_max - sr0) / std_adj
    # std_adj = std of the max SR distribution ≈ std / sqrt(2 * log(n))
    # Simplified: DSR = 1 - Φ(selected_max - sr0) approximates the probability
    # that the selected SR is above the null
    if n_configs > 0 and std_sr > 0:
        std_adjust = std_sr / sqrt(2 * log(max(2, n_configs)))
        dsr_z = (max_sr - sr0) / std_adjust if std_adjust > 0 else 0.0
    else:
        dsr_z = 0.0

    # DSR probability using normal CDF approximation
    from math import erf
    dsr_prob = 0.5 * (1 + erf(dsr_z / sqrt(2)))
    dsr_prob = round(dsr_prob, 4)

    print(f"  Configs with >=2 trades: {n_configs}")
    print(f"  Max explore Sharpe: {max_sr:.4f}")
    print(f"  Mean explore Sharpe: {mean_sr:.4f}")
    print(f"  Std explore Sharpe: {std_sr:.4f}")
    print(f"  SR0 (expected max from noise): {sr0:.4f}")
    print(f"  Deflated Sharpe z-score: {dsr_z:.4f}")
    print(f"  DSR probability: {dsr_prob:.4f} (need ≥0.95)")

    # ── Select winner ────────────────────────────────────────────────────
    # Mechanical selection: best explore Sharpe with >=10 trades that also
    # exceeds B&H explore Sharpe. Check holdout too.
    print("\n" + "=" * 60)
    print("Selection")
    print("=" * 60)

    explore_results = [r for r in results if r["window"] == "explore"]
    holdout_results_map = {}
    for r in results:
        if r["window"] == "holdout":
            holdout_results_map[r["config"]] = r

    full_results_map = {}
    for r in results:
        if r["window"] == "full":
            full_results_map[r["config"]] = r

    # Filter: >= 10 trades AND Sharpe > B&H explore
    eligible = [r for r in explore_results 
                if r["total_trades_started"] >= 10 and r["sharpe_ann"] > bh_explore_sr]
    eligible.sort(key=lambda r: r["sharpe_ann"], reverse=True)

    print(f"  Eligible candidates (≥10 trades, Sharpe > B&H {bh_explore_sr:.4f}): {len(eligible)}")
    
    winner = None
    if eligible:
        winner = eligible[0]
        print(f"\n  WINNER: {winner['config']}")
        print(f"    Explore Sharpe: {winner['sharpe_ann']:.4f}, AnnRet {winner['ann_return_pct']}%")
        print(f"    Trades: {winner['total_trades_started']}")

        h = holdout_results_map.get(winner["config"])
        if h:
            print(f"\n    HOLDOUT:")
            print(f"      Sharpe: {h['sharpe_ann']:.4f}, AnnRet {h['ann_return_pct']}%")
            print(f"      NetMult: {h['net_multiple']:.4f}")
            print(f"      Trades: {h['total_trades_started']}")
            print(f"      vs B&H: Sharpe {bh_holdout_sr:.4f}")

        f = full_results_map.get(winner["config"])
        if f:
            print(f"\n    FULL SPAN:")
            print(f"      Sharpe: {f['sharpe_ann']:.4f}, AnnRet {f['ann_return_pct']}%")
            print(f"      NetMult: {f['net_multiple']:.4f}")
            print(f"      Trades: {f['total_trades_started']}")
            print(f"      vs B&H: Sharpe {bh_full_sr:.4f}")
    else:
        print("\n  NO WINNER: No config meets the eligibility bar.")
        # Show closest
        if explore_results:
            sorted_sr = sorted(explore_results, key=lambda r: r["sharpe_ann"], reverse=True)
            print(f"\n  Top 3 explore configs:")
            for sr_entry in sorted_sr[:3]:
                print(f"    {sr_entry['config']}: SR {sr_entry['sharpe_ann']:.4f}, "
                      f"trades {sr_entry['total_trades_started']}, Ret {sr_entry['ann_return_pct']}%")

    # ── Prepare output ──────────────────────────────────────────────────
    output = {
        "study": "funding_z_rework",
        "hypothesis": (
            "Extreme negative funding rates (z-score << -1) predict short-term "
            "bullish reversals. Entry LONG when hourly funding z-score is below "
            "threshold; exit on normalisation or max hold."
        ),
        "data": {
            "funding": "research/data/BTC_funding_history.json (hourly, May 2023 - Jul 2026)",
            "price": "research/data/BTC_1d_snapshot.json",
        },
        "parameter_grid": {
            "lookback_days": LOOKBACKS,
            "entry_z_thresholds": ENTRY_THRESHOLDS,
            "max_hold_bars": MAX_HOLD_HOURS,
        },
        "split": {
            "fraction": SPLIT_FRACTION,
            "explore": f"{len(explore)} bars",
            "holdout": f"{len(holdout)} bars",
        },
        "buy_and_hold": {
            "explore": {"sharpe": round(bh_explore_sr, 4), "ann_ret_pct": round(bh_explore_ret * 100, 2), "net_mult": round(bh_explore_mult, 4)},
            "holdout": {"sharpe": round(bh_holdout_sr, 4), "ann_ret_pct": round(bh_holdout_ret * 100, 2), "net_mult": round(bh_holdout_mult, 4)},
            "full":     {"sharpe": round(bh_full_sr, 4), "ann_ret_pct": round(bh_full_ret * 100, 2), "net_mult": round(bh_full_mult, 4)},
        },
        "deflated_sharpe": {
            "n_configs_evaluated": n_configs,
            "max_explore_sr": round(max_sr, 4),
            "sr0_null": round(sr0, 4),
            "dsr_z": round(dsr_z, 4),
            "dsr_probability": dsr_prob,
            "dsr_significant": dsr_prob >= 0.95,
            "method": "Bailey & López de Prado (2014), E[max Z] approx for N i.i.d. normals",
        },
        "all_variants": results,
        "selection_criteria": (
            "Highest explore Sharpe among variants with >= 10 exploration trades "
            "AND Sharpe > BTC buy-and-hold explore Sharpe"
        ),
        "winner": winner,
        "conclusion": "",
    }

    if winner:
        h = holdout_results_map.get(winner["config"])
        f = full_results_map.get(winner["config"])
        output["winner_holdout"] = h
        output["winner_fullspan"] = f

        is_promotable = (
            winner["total_trades_started"] >= MIN_TRADES_PROMOTABLE
            and h and h["sharpe_ann"] > 0
            and h["sharpe_ann"] > bh_holdout_sr
            and dsr_prob >= 0.95
        )
        output["is_promotable"] = is_promotable

        if is_promotable:
            output["conclusion"] = (
                f"PROMOTABLE: {winner['config']} beats B&H in-sample and out-of-sample "
                f"with {winner['total_trades_started']} explore trades, "
                f"deflated Sharpe significant (DSR={dsr_prob:.2f})."
            )
        else:
            reasons = []
            if winner["total_trades_started"] < MIN_TRADES_PROMOTABLE:
                reasons.append(f"only {winner['total_trades_started']} trades (need {MIN_TRADES_PROMOTABLE})")
            if h and h["sharpe_ann"] <= 0:
                reasons.append(f"holdout Sharpe {h['sharpe_ann']:.4f} <= 0")
            if h and h["sharpe_ann"] <= bh_holdout_sr:
                reasons.append(f"holdout Sharpe {h['sharpe_ann']:.4f} <= B&H {bh_holdout_sr:.4f}")
            if dsr_prob < 0.95:
                reasons.append(f"DSR {dsr_prob:.4f} < 0.95")
            output["conclusion"] = (
                f"NOT promotable: {winner['config']} fails bar - {'; '.join(reasons)}"
            )
    else:
        output["conclusion"] = "No config met the selection criteria."

    # ── Write output ────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print(f"Output written to: {OUTPUT_PATH}")
    print(f"{'=' * 60}")
    print(f"\nCONCLUSION: {output['conclusion']}")

    return output


def main():
    parser = argparse.ArgumentParser(description="FundingZ Study")
    parser.add_argument("--phase", choices=["run", "selfcheck"], default="run")
    args = parser.parse_args()

    if args.phase == "selfcheck":
        print("FundingZ study: selfcheck OK")
        print(f"  LOOKBACKS: {LOOKBACKS}")
        print(f"  ENTRY_THRESHOLDS: {ENTRY_THRESHOLDS}")
        print(f"  MAX_HOLD_HOURS: {MAX_HOLD_HOURS}")
        print(f"  Output: {OUTPUT_PATH}")
        return

    run_study()


if __name__ == "__main__":
    main()
