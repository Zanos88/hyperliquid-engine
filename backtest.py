"""Walk-forward backtest — replays Hyperliquid history through the EXACT
live strategy code (strategy.signals.evaluate_signal, same edge-trigger
alignment as main.py, same R:R gate, same 300-bar slices the engine uses).

HONESTY CONTRACT (print + store with every run):
- SIMULATED results. Fills are idealized at the exact touch price; real
  fills have slippage and funding costs that are NOT modeled.
- Candle-granularity ambiguity: if one candle touches BOTH stop and
  target, the STOP is assumed to fill first (conservative).
- Taker fees modeled at 0.075% per side (verified Propr rate).
- History window is capped by Hyperliquid's 5,000-candle retention on
  the trigger timeframe (~208 days for 1h; ~2.3yr for 4h).
- Past confluence behavior does not promise future results; this data
  informs indicator review, it does not "validate" the strategy.

Usage:
    # single run
    railway run --service btc-signal-bot python backtest.py \
        [--bias-tf 4h] [--trigger-tf 1h] [--indicators default|all|csv] \
        [--stop-model structural|hybrid] [--atr-multiplier 1.5] [--no-store]

    # config-driven batch sweep (one stored run per combo)
    railway run --service btc-signal-bot python backtest.py --sweep sweep_config.yaml
"""
from __future__ import annotations

import argparse
import json
import math
import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml
from ulid import ULID

from data.feed import Candle, fetch_candles
from strategy.signals import (
    DEFAULT_ATR_MULTIPLIER,
    DEFAULT_INDICATOR_CONFIG,
    FISHER4H_EXHAUSTION_THRESHOLD,
    INDICATOR_NAMES,
    Signal,
    SignalDirection,
    SuppressedSignal,
    evaluate_signal,
)
from strategy.timeframes import LOOKBACK_BARS, interval_seconds, validate_combo
from strategy.trigger_1h import fisher_transform

TAKER_FEE = 0.00075  # per side, verified in RESEARCH_FINDINGS Rev 3
WARMUP_TRIGGER_BARS = 40      # fisher(10) + obv sma(20) + atr(14) + margin
WARMUP_BIAS_BARS = 120        # fractal/S-R structure + ichimoku(52+disp)


@dataclass
class TradeResult:
    entry_ts: datetime
    exit_ts: datetime | None
    direction: str
    entry: float
    stop: float
    target: float
    reward_risk: float
    exit_reason: str  # target | stop | unresolved
    gross_r: float | None
    net_r: float | None
    bars_held: int
    indicators_snapshot: dict


def simulate_outcome(
    candles: list[Candle],
    entry_index: int,
    signal: Signal,
    fisher4h_exit: bool = False,
    fisher4h_series: list[tuple[int, float]] | None = None,
    exhaustion_threshold: float = FISHER4H_EXHAUSTION_THRESHOLD,
) -> TradeResult:
    """Walk candles AFTER entry until stop or target is TOUCHED (high/low,
    not close). Both touched in one candle -> stop first (conservative).
    Runs out of data -> unresolved (excluded from win/loss stats).

    fisher4h_exit (BACKTEST-ONLY variant): additionally exit at a trigger
    bar's CLOSE when the 4H Fisher crosses INTO extended territory in the
    trade's favor (LONG: F crosses >= +threshold; SHORT: <= -threshold) —
    the move you're in looks exhausted, scale out ahead of the structural
    target. Edge semantics: already-extended-at-entry never fires until
    Fisher leaves and re-enters the extended zone. Stop/target touches in
    the same bar take precedence (conservative). fisher4h_series is
    [(close_time_ms, fisher_value), ...] for CLOSED 4h bars, ascending —
    the Fisher construction is causal, so a precomputed series is
    lookahead-safe."""
    if fisher4h_exit and not fisher4h_series:
        raise ValueError("fisher4h_exit requires fisher4h_series")
    is_long = signal.direction == SignalDirection.LONG
    risk = abs(signal.entry - signal.stop)
    entry_ts = datetime.fromtimestamp(candles[entry_index].close_time_ms / 1000, tz=timezone.utc)

    def _in_favor(f: float) -> bool:
        return f >= exhaustion_threshold if is_long else f <= -exhaustion_threshold

    def _result(j: int, exit_price: float, reason: str) -> TradeResult:
        sign = 1 if is_long else -1
        gross_r = sign * (exit_price - signal.entry) / risk
        fee_r = (signal.entry + exit_price) * TAKER_FEE / risk
        return TradeResult(
            entry_ts=entry_ts,
            exit_ts=datetime.fromtimestamp(candles[j].close_time_ms / 1000, tz=timezone.utc),
            direction=signal.direction.value, entry=signal.entry, stop=signal.stop,
            target=signal.target, reward_risk=signal.reward_risk, exit_reason=reason,
            gross_r=gross_r, net_r=gross_r - fee_r, bars_held=j - entry_index,
            indicators_snapshot={},
        )

    # index of the first 4h bar NOT yet closed at entry
    k = 0
    if fisher4h_exit:
        entry_close_ms = candles[entry_index].close_time_ms
        while k < len(fisher4h_series) and fisher4h_series[k][0] <= entry_close_ms:
            k += 1

    for j in range(entry_index + 1, len(candles)):
        c = candles[j]
        hit_stop = c.low <= signal.stop if is_long else c.high >= signal.stop
        hit_target = c.high >= signal.target if is_long else c.low <= signal.target
        if hit_stop or hit_target:
            exit_price = signal.stop if hit_stop else signal.target  # stop wins ambiguity
            return _result(j, exit_price, "stop" if hit_stop else "target")

        if fisher4h_exit:
            crossed = False
            while k < len(fisher4h_series) and fisher4h_series[k][0] <= c.close_time_ms:
                now_f = fisher4h_series[k][1]
                prev_f = fisher4h_series[k - 1][1] if k >= 1 else 0.0
                if _in_favor(now_f) and not _in_favor(prev_f):
                    crossed = True
                k += 1
            if crossed:
                return _result(j, c.close, "fisher_exhaustion")

    return TradeResult(entry_ts=entry_ts, exit_ts=None, direction=signal.direction.value,
                       entry=signal.entry, stop=signal.stop, target=signal.target,
                       reward_risk=signal.reward_risk, exit_reason="unresolved",
                       gross_r=None, net_r=None, bars_held=len(candles) - 1 - entry_index,
                       indicators_snapshot={})


def bias_slice_no_lookahead(bias_candles: list[Candle], trigger_close_ms: int) -> list[Candle]:
    """Only bias candles CLOSED at/before the trigger close — no lookahead."""
    return [c for c in bias_candles if c.close_time_ms <= trigger_close_ms]


def log_return_stats(candles: list[Candle]) -> dict:
    """Real close-to-close log-return distribution of the series actually
    used — mean/stdev/excess kurtosis/N. Replaces the REJECTED external
    stats table from the volatility research doc with sourced numbers
    (source: the Hyperliquid candles this very run consumed)."""
    closes = [c.close for c in candles]
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]
    n = len(rets)
    if n < 2:
        return {"n": n}
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    m2 = sum((r - mean) ** 2 for r in rets) / n
    m4 = sum((r - mean) ** 4 for r in rets) / n
    return {
        "n": n,
        "mean": mean,
        "stdev": math.sqrt(var),
        "excess_kurtosis": (m4 / (m2 * m2) - 3.0) if m2 > 0 else None,
    }


def run_backtest(bias_candles: list[Candle], trigger_candles: list[Candle],
                 config: dict, ichimoku_variant: str = "standard",
                 stop_model: str = "structural",
                 atr_multiplier: float = DEFAULT_ATR_MULTIPLIER,
                 fisher4h_entry: bool = False,
                 fisher4h_exit: bool = False,
                 exhaustion_threshold: float = FISHER4H_EXHAUSTION_THRESHOLD,
                 candles_4h: list[Candle] | None = None) -> dict:
    """Walk-forward over trigger closes; mirrors main.py exactly:
    300-bar slices, edge-triggered alignment, one open trade at a time
    (max_concurrent=1, the live default).

    fisher4h_entry/fisher4h_exit are the BACKTEST-ONLY V2.2 exhaustion
    variants; both need candles_4h (a dedicated 4h series regardless of
    the TF pair — the heuristic is specifically about the 4H chart)."""
    fisher4h_series: list[tuple[int, float]] = []
    close_ms_4h: list[int] = []
    if fisher4h_entry or fisher4h_exit:
        if not candles_4h:
            raise ValueError("fisher4h variants require candles_4h")
        fisher_line = fisher_transform(candles_4h)[0]  # causal -> precompute is lookahead-safe
        close_ms_4h = [c.close_time_ms for c in candles_4h]
        fisher4h_series = list(zip(close_ms_4h, fisher_line))

    def _fisher4h_at(trigger_close_ms: int) -> float:
        """Fisher of the last 4h bar CLOSED at/before this trigger close."""
        idx = bisect_right(close_ms_4h, trigger_close_ms) - 1
        return fisher4h_series[idx][1] if idx >= 0 else 0.0

    trades: list[TradeResult] = []
    suppressed = 0
    suppressed_exhaustion = 0
    prev_alignment: str | None = None
    open_until_index = -1  # enforce one-position-at-a-time like the live gate

    for i in range(WARMUP_TRIGGER_BARS, len(trigger_candles)):
        trig_slice = trigger_candles[max(0, i + 1 - LOOKBACK_BARS): i + 1]
        bias_all = bias_slice_no_lookahead(bias_candles, trigger_candles[i].close_time_ms)
        if len(bias_all) < WARMUP_BIAS_BARS:
            continue
        bias_slice = bias_all[-LOOKBACK_BARS:]

        result, readings = evaluate_signal(
            bias_slice, trig_slice, config=config,
            ichimoku_variant=ichimoku_variant, return_readings=True,
            stop_model=stop_model, atr_multiplier=atr_multiplier,
            fisher4h_entry_filter=fisher4h_entry,
            fisher4h_value=(_fisher4h_at(trigger_candles[i].close_time_ms)
                            if fisher4h_entry else None),
            exhaustion_threshold=exhaustion_threshold,
        )

        enabled_votes = [r["vote"] for n, r in readings.items() if r["enabled"]]
        alignment = (enabled_votes[0] if enabled_votes
                     and all(v == enabled_votes[0] for v in enabled_votes)
                     and enabled_votes[0] != "NONE" else None)
        is_new_alignment = alignment is not None and alignment != prev_alignment
        prev_alignment = alignment

        if not is_new_alignment or i <= open_until_index:
            continue
        if isinstance(result, SuppressedSignal):
            if result.kind == "fisher4h_exhaustion":
                suppressed_exhaustion += 1
            else:
                suppressed += 1
            continue
        if isinstance(result, Signal):
            trade = simulate_outcome(trigger_candles, i, result,
                                     fisher4h_exit=fisher4h_exit,
                                     fisher4h_series=fisher4h_series,
                                     exhaustion_threshold=exhaustion_threshold)
            trade.indicators_snapshot = readings
            trades.append(trade)
            # block new entries until this trade resolves (or forever if unresolved)
            if trade.exit_ts is not None:
                open_until_index = i + trade.bars_held
            else:
                open_until_index = len(trigger_candles)

    resolved = [t for t in trades if t.exit_reason != "unresolved"]
    wins = [t for t in resolved if t.net_r is not None and t.net_r > 0]
    losses = [t for t in resolved if t.net_r is not None and t.net_r <= 0]
    net_rs = [t.net_r for t in resolved if t.net_r is not None]

    equity_r, peak, max_dd = 0.0, 0.0, 0.0
    for r in net_rs:
        equity_r += r
        peak = max(peak, equity_r)
        max_dd = max(max_dd, peak - equity_r)

    gross_win = sum(t.net_r for t in wins) if wins else 0.0
    gross_loss = abs(sum(t.net_r for t in losses)) if losses else 0.0

    return {
        "bars_evaluated": len(trigger_candles) - WARMUP_TRIGGER_BARS,
        "trades": trades,
        "resolved": len(resolved),
        "wins": len(wins),
        "losses": len(losses),
        "unresolved": len(trades) - len(resolved),
        "suppressed_rr": suppressed,
        "suppressed_exhaustion": suppressed_exhaustion,
        "gross_r": sum(t.gross_r for t in resolved if t.gross_r is not None),
        "net_r": sum(net_rs),
        "avg_net_r": (sum(net_rs) / len(net_rs)) if net_rs else None,
        "win_rate": (len(wins) / len(resolved)) if resolved else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "max_drawdown_r": max_dd,
    }


def _parse_indicators(spec: str) -> dict:
    if spec == "default":
        return dict(DEFAULT_INDICATOR_CONFIG)
    if spec == "all":
        return {n: True for n in INDICATOR_NAMES}
    chosen = {s.strip() for s in spec.split(",")}
    unknown = chosen - set(INDICATOR_NAMES)
    if unknown:
        raise SystemExit(f"unknown indicators: {unknown}")
    return {n: (n in chosen) for n in INDICATOR_NAMES}


CAVEATS = ("caveats: idealized touch fills, no slippage/funding, stop-first on "
           "ambiguous candles, taker fees 0.075%/side, window limited to most "
           "recent 5,000 trigger candles.")


def _window(trigger_candles: list[Candle]) -> tuple[datetime, datetime]:
    t0 = datetime.fromtimestamp(trigger_candles[0].open_time_ms / 1000, tz=timezone.utc)
    t1 = datetime.fromtimestamp(trigger_candles[-1].close_time_ms / 1000, tz=timezone.utc)
    return t0, t1


def store_run(conn, run_id: str, bias_tf: str, trigger_tf: str, config: dict,
              t0: datetime, t1: datetime, summary: dict,
              trades: list[TradeResult], notes: dict) -> None:
    conn.execute(
        """INSERT INTO backtest_runs (run_id, bias_tf, trigger_tf, indicator_config,
               candles_from, candles_to, bars_evaluated, trades, wins, losses,
               unresolved, suppressed_rr, gross_r, net_r, avg_net_r, win_rate,
               profit_factor, max_drawdown_r, fees_model, notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (run_id, bias_tf, trigger_tf, json.dumps(config), t0, t1,
         summary["bars_evaluated"], len(trades), summary["wins"], summary["losses"],
         summary["unresolved"], summary["suppressed_rr"], summary["gross_r"],
         summary["net_r"], summary["avg_net_r"], summary["win_rate"],
         summary["profit_factor"], summary["max_drawdown_r"],
         "taker 0.075%/side, no slippage/funding",
         json.dumps(notes, default=str)),
    )
    for t in trades:
        conn.execute(
            """INSERT INTO backtest_trades (run_id, entry_ts, exit_ts, direction,
                   entry, stop, target, reward_risk, exit_reason, gross_r, net_r,
                   bars_held, indicators_snapshot)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, t.entry_ts, t.exit_ts, t.direction, t.entry, t.stop, t.target,
             t.reward_risk, t.exit_reason, t.gross_r, t.net_r, t.bars_held,
             json.dumps(t.indicators_snapshot, default=str)),
        )


def _summary_row(summary: dict) -> str:
    wr = f"{summary['win_rate']:.0%}" if summary["win_rate"] is not None else "-"
    pf = f"{summary['profit_factor']:.2f}" if summary["profit_factor"] is not None else "-"
    return (f"trades {len(summary['trades']):>3} | "
            f"W-L {summary['wins']}-{summary['losses']} | wr {wr:>4} | "
            f"net {summary['net_r']:+7.2f}R | PF {pf:>5} | "
            f"maxDD {summary['max_drawdown_r']:5.2f}R | "
            f"supp_rr {summary['suppressed_rr']}")


# ── single-run mode ──

def run_single(args) -> None:
    config = _parse_indicators(args.indicators)
    now_ms = int(time.time() * 1000)
    span = lambda tf: 5000 * interval_seconds(tf) * 1000

    print(f"fetching history: bias {args.bias_tf}, trigger {args.trigger_tf} ...")
    bias_candles = fetch_candles("BTC", args.bias_tf, now_ms - span(args.bias_tf), now_ms)
    trigger_candles = fetch_candles("BTC", args.trigger_tf, now_ms - span(args.trigger_tf), now_ms)
    t0, t1 = _window(trigger_candles)
    print(f"  {len(bias_candles)} bias candles, {len(trigger_candles)} trigger candles "
          f"({t0:%Y-%m-%d} -> {t1:%Y-%m-%d})")

    candles_4h = None
    if args.fisher4h_entry or args.fisher4h_exit:
        candles_4h = (bias_candles if args.bias_tf == "4h"
                      else trigger_candles if args.trigger_tf == "4h"
                      else fetch_candles("BTC", "4h", now_ms - span("4h"), now_ms))

    summary = run_backtest(bias_candles, trigger_candles, config, args.ichimoku_variant,
                           stop_model=args.stop_model, atr_multiplier=args.atr_multiplier,
                           fisher4h_entry=args.fisher4h_entry, fisher4h_exit=args.fisher4h_exit,
                           exhaustion_threshold=args.exhaustion_threshold,
                           candles_4h=candles_4h)
    trades = summary.pop("trades")

    print("\n=== SIMULATED BACKTEST RESULT (not live performance) ===")
    print(f"combo: {args.bias_tf} bias / {args.trigger_tf} trigger | indicators: "
          + "+".join(n for n, v in config.items() if v)
          + f" | stop: {args.stop_model}"
          + (f"@{args.atr_multiplier}" if args.stop_model == "hybrid" else "")
          + (f" | fisher4h E={args.fisher4h_entry} X={args.fisher4h_exit}"
             f"@{args.exhaustion_threshold}"
             if (args.fisher4h_entry or args.fisher4h_exit) else ""))
    print(f"window: {t0:%Y-%m-%d} -> {t1:%Y-%m-%d} | bars evaluated: {summary['bars_evaluated']}")
    print(f"signals taken: {len(trades)} (resolved {summary['resolved']}, "
          f"unresolved {summary['unresolved']}) | suppressed by R:R gate: {summary['suppressed_rr']}"
          + (f" | by 4H exhaustion: {summary['suppressed_exhaustion']}"
             if summary["suppressed_exhaustion"] else ""))
    if summary["resolved"]:
        print(f"wins {summary['wins']} / losses {summary['losses']} "
              f"(win rate {summary['win_rate']:.1%})")
        print(f"net {summary['net_r']:+.2f}R total | avg {summary['avg_net_r']:+.3f}R/trade | "
              f"profit factor {summary['profit_factor'] and round(summary['profit_factor'], 2)} | "
              f"max drawdown {summary['max_drawdown_r']:.2f}R")
    else:
        print("no resolved trades in window -- insufficient data, no conclusions")
    print(CAVEATS)

    if not args.no_store:
        from db.store import TelemetryStore
        store = TelemetryStore()
        run_id = str(ULID())
        notes = {
            "kind": "SIMULATED walk-forward via live strategy code",
            "stop_model": args.stop_model,
            "atr_multiplier": args.atr_multiplier if args.stop_model == "hybrid" else None,
            "fisher4h_entry": args.fisher4h_entry,
            "fisher4h_exit": args.fisher4h_exit,
            "exhaustion_threshold": (args.exhaustion_threshold
                                     if (args.fisher4h_entry or args.fisher4h_exit) else None),
            "suppressed_exhaustion": summary["suppressed_exhaustion"],
            "return_stats": {args.bias_tf: log_return_stats(bias_candles),
                             args.trigger_tf: log_return_stats(trigger_candles)},
        }
        store_run(store._connect(), run_id, args.bias_tf, args.trigger_tf, config,
                  t0, t1, summary, trades, notes)
        print(f"stored: run_id={run_id} ({len(trades)} trades) in backtest_runs/backtest_trades")


# ── sweep mode ──

def expand_sweep(cfg: dict) -> list[dict]:
    """Cross-product expansion per grid. Config-driven so future sweeps
    are a YAML edit, not a code change. A grid without a fisher4h key
    runs with both exhaustion mechanisms off; entries with either
    mechanism on expand once per listed threshold."""
    combos: list[dict] = []
    for grid in cfg["grids"]:
        fisher_variants = grid.get("fisher4h", [{"entry": False, "exit": False}])
        for tf in grid["tf_pairs"]:
            validate_combo(tf["bias"], tf["trigger"])
            for ind in grid["indicator_sets"]:
                for sm in grid["stop_models"]:
                    if sm["model"] == "hybrid":
                        mult = sm.get("atr_multiplier")
                        if mult is None:
                            raise SystemExit("hybrid stop_model entries need atr_multiplier")
                    else:
                        mult = None
                    for fv in fisher_variants:
                        entry, exit_ = bool(fv.get("entry")), bool(fv.get("exit"))
                        thresholds = fv.get("thresholds", [FISHER4H_EXHAUSTION_THRESHOLD]) \
                            if (entry or exit_) else [None]
                        for thr in thresholds:
                            combos.append({
                                "grid": grid["name"],
                                "bias_tf": tf["bias"], "trigger_tf": tf["trigger"],
                                "indicators": ind,
                                "stop_model": sm["model"], "atr_multiplier": mult,
                                "fisher4h_entry": entry, "fisher4h_exit": exit_,
                                "exhaustion_threshold": thr,
                            })
    return combos


def _fisher_label(c: dict) -> str:
    if not (c["fisher4h_entry"] or c["fisher4h_exit"]):
        return "off"
    parts = ("E" if c["fisher4h_entry"] else "") + ("X" if c["fisher4h_exit"] else "")
    return f"{parts}@{c['exhaustion_threshold']}"


def _combo_label(c: dict) -> str:
    stop = c["stop_model"] + (f"@{c['atr_multiplier']}" if c["atr_multiplier"] else "")
    return (f"{c['bias_tf']}/{c['trigger_tf']} | {c['indicators']:<24} | "
            f"{stop:<14} | f4h {_fisher_label(c):<7}")


def run_sweep(args) -> None:
    with open(args.sweep, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    combos = expand_sweep(cfg)
    sweep_id = str(ULID())
    print(f"sweep {cfg.get('sweep_name', 'unnamed')} | {len(combos)} runs | sweep_id={sweep_id}")

    # fetch each unique TF ONCE — consistent windows across every run.
    # 4h is always included when any combo runs a fisher4h variant (the
    # exhaustion heuristic reads the 4H chart regardless of the TF pair).
    now_ms = int(time.time() * 1000)
    span = lambda tf: 5000 * interval_seconds(tf) * 1000
    unique_tfs = {c["bias_tf"] for c in combos} | {c["trigger_tf"] for c in combos}
    if any(c["fisher4h_entry"] or c["fisher4h_exit"] for c in combos):
        unique_tfs.add("4h")
    unique_tfs = sorted(unique_tfs, key=interval_seconds)
    candles: dict[str, list[Candle]] = {}
    for tf in unique_tfs:
        candles[tf] = fetch_candles("BTC", tf, now_ms - span(tf), now_ms)
        t0, t1 = _window(candles[tf])
        print(f"  fetched {tf}: {len(candles[tf])} candles ({t0:%Y-%m-%d} -> {t1:%Y-%m-%d})")
    stats = {tf: log_return_stats(candles[tf]) for tf in unique_tfs}

    store_conn = None
    if not args.no_store:
        from db.store import TelemetryStore
        store_conn = TelemetryStore()._connect()

    results: list[tuple[dict, dict, str]] = []
    for idx, combo in enumerate(combos, 1):
        config = _parse_indicators(combo["indicators"])
        summary = run_backtest(
            candles[combo["bias_tf"]], candles[combo["trigger_tf"]], config,
            stop_model=combo["stop_model"],
            atr_multiplier=combo["atr_multiplier"] or DEFAULT_ATR_MULTIPLIER,
            fisher4h_entry=combo["fisher4h_entry"],
            fisher4h_exit=combo["fisher4h_exit"],
            exhaustion_threshold=combo["exhaustion_threshold"] or FISHER4H_EXHAUSTION_THRESHOLD,
            candles_4h=candles.get("4h"),
        )
        trades = summary["trades"]
        run_id = str(ULID())
        if store_conn is not None:
            t0, t1 = _window(candles[combo["trigger_tf"]])
            notes = {
                "kind": "SIMULATED walk-forward via live strategy code",
                "sweep_id": sweep_id, "grid": combo["grid"],
                "stop_model": combo["stop_model"],
                "atr_multiplier": combo["atr_multiplier"],
                "fisher4h_entry": combo["fisher4h_entry"],
                "fisher4h_exit": combo["fisher4h_exit"],
                "exhaustion_threshold": combo["exhaustion_threshold"],
                "suppressed_exhaustion": summary["suppressed_exhaustion"],
                "return_stats": {combo["bias_tf"]: stats[combo["bias_tf"]],
                                 combo["trigger_tf"]: stats[combo["trigger_tf"]]},
            }
            store_run(store_conn, run_id, combo["bias_tf"], combo["trigger_tf"], config,
                      t0, t1, summary, trades, notes)
        print(f"[{idx:>3}/{len(combos)}] {_combo_label(combo)} | {_summary_row(summary)}")
        results.append((combo, summary, run_id))

    print("\n=== SIMULATED SWEEP COMPARISON (not live performance) ===")
    print(f"sweep_id={sweep_id} | runs={len(results)}")
    header = (f"{'grid':<14} {'tfs':<9} {'indicators':<24} {'stop':<14} {'f4h':<8} "
              f"{'trades':>6} {'W-L':>7} {'netR':>8} {'PF':>6} {'maxDD':>7} "
              f"{'supp_rr':>8} {'supp_exh':>9}")
    print(header)
    print("-" * len(header))
    for combo, summary, _ in results:
        pf = summary["profit_factor"]
        stop = combo["stop_model"] + (f"@{combo['atr_multiplier']}" if combo["atr_multiplier"] else "")
        print(f"{combo['grid']:<14} {combo['bias_tf'] + '/' + combo['trigger_tf']:<9} "
              f"{combo['indicators']:<24} {stop:<14} {_fisher_label(combo):<8} "
              f"{len(summary['trades']):>6} {str(summary['wins']) + '-' + str(summary['losses']):>7} "
              f"{summary['net_r']:>+8.2f} {(f'{pf:.2f}' if pf is not None else '-'):>6} "
              f"{summary['max_drawdown_r']:>7.2f} {summary['suppressed_rr']:>8} "
              f"{summary['suppressed_exhaustion']:>9}")
    print(CAVEATS)
    if store_conn is not None:
        print(f"stored: {len(results)} runs under sweep_id={sweep_id} in backtest_runs/backtest_trades")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", help="YAML sweep config; runs a batch instead of a single backtest")
    ap.add_argument("--bias-tf", default="4h")
    ap.add_argument("--trigger-tf", default="1h")
    ap.add_argument("--indicators", default="default")
    ap.add_argument("--ichimoku-variant", default="standard")
    ap.add_argument("--stop-model", default="structural", choices=("structural", "hybrid"))
    ap.add_argument("--atr-multiplier", type=float, default=DEFAULT_ATR_MULTIPLIER)
    ap.add_argument("--fisher4h-entry", action="store_true",
                    help="suppress entries when 4H Fisher already extended in signal direction")
    ap.add_argument("--fisher4h-exit", action="store_true",
                    help="exit open sim positions when 4H Fisher crosses extended in trade's favor")
    ap.add_argument("--exhaustion-threshold", type=float, default=FISHER4H_EXHAUSTION_THRESHOLD)
    ap.add_argument("--no-store", action="store_true")
    args = ap.parse_args()

    if args.sweep:
        run_sweep(args)
    else:
        run_single(args)


if __name__ == "__main__":
    main()
