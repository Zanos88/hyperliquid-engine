"""Track 4 — unconstrained mean-reversion (Fisher-4H exhaustion + SMA bias).

BACKTEST ONLY. Spot-capital context, EXPLICITLY NOT CHALLENGE-RELEVANT:
no stop exists, so worst-case loss is unbounded by design — max adverse
excursion (MAE) is reported per trade with the same prominence as P&L.
Depends on the Fisher fix (9da31ee) — refuses to run if the buggy
coefficient is detected.

Grid (24 runs, sized up front per the brief; position size is a pure
scaling of the same trade list, so 5%/10% are REPORTING COLUMNS, not run
axes): bias TF {1d, 12h} x SMA window {30, 50} x entry threshold
{2.0, 3.0} x hold cap {none, 14d, 30d}.

Rules (pre-registered):
  Entry  LONG when 4H Fisher <= -thr AND bias close > SMA(window);
         SHORT mirrored (Fisher >= +thr AND close < SMA). One open trade
         at a time. Entry/exit at bar close, fee 0.075%/side.
  Exit   first of: (a) reversion - close beats entry by the round-trip
         fee cost (trade net-profitable, the literal "closed once profit
         hits"); (b) Fisher-reversal - Fisher crosses back through +/-1.5
         (single pre-registered level: corrected 4H Fisher exceeds 2.0 on
         only ~0.2% of bars, so a 2.0 exit would almost never fire);
         (c) time cap (holding-period ceiling, NOT a price stop). Both
         (a)/(b) flags logged when they coincide.
  Sizing fixed % of INITIAL capital per trade (non-compounding), so
         worst-case $ figures are linear and transparent.

Usage: python scripts/track4_mean_reversion.py --phase {selfcheck,run}
Output: research/output/track4_results.json + stdout tables (no DB —
P&L here is %-of-capital, not R; backtest_runs' R-schema doesn't apply).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import DATA_DIR, OUTPUT_DIR, load_snapshot  # noqa: E402
from data.feed import Candle  # noqa: E402
from strategy.trigger_1h import fisher_transform, sma  # noqa: E402

BIAS_TFS = ("1d", "12h")
SMA_WINDOWS = (30, 50)
ENTRY_THRESHOLDS = (2.0, 3.0)
HOLD_CAPS_DAYS = (None, 14, 30)
SIZES_PCT = (5.0, 10.0)          # reporting columns
FEE = 0.00075                    # 0.075%/side
REVERSAL_EXIT_LEVEL = 1.5
WARMUP_4H = 60
START_CAPITAL = 100_000.0
BARS_PER_DAY_4H = 6

OUT = OUTPUT_DIR / "track4_results.json"


def _ms_to_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def bias_direction_series(bias_candles: list[Candle], window: int) -> tuple[list[int], list[int]]:
    closes = [c.close for c in bias_candles]
    s = sma(closes, window)
    # sma() passes values through during warm-up — treat warm-up as no-bias.
    dirs = [0 if i < window - 1 else (1 if closes[i] > s[i] else (-1 if closes[i] < s[i] else 0))
            for i in range(len(closes))]
    return dirs, [c.close_time_ms for c in bias_candles]


def run_config(candles_4h, fisher, bias_dirs, bias_close_ms, thr, cap_days,
               long_only: bool = False, exit_mode: str = "first_profit",
               atr_series=None, tp_atr_mult: float = 1.0,
               stop_atr_mult: float | None = None) -> list[dict]:
    cap_bars = cap_days * BARS_PER_DAY_4H if cap_days else None
    trades: list[dict] = []
    open_t: dict | None = None
    for i in range(WARMUP_4H, len(candles_4h)):
        c = candles_4h[i]
        if open_t is not None:
            side = open_t["side"]
            e = open_t["entry"]
            # Track 4-Comp: ATR stop, checked FIRST (program stop-first
            # convention), filled AT the stop level. Long-only variant.
            if stop_atr_mult is not None and side == "LONG":
                lvl = open_t["stop_level"]
                if c.low <= lvl:
                    net = (lvl / e - 1) - 2 * FEE
                    open_t["mae"] = min(open_t["mae"], lvl / e - 1)
                    open_t.update(exit_i=i, exit_ts=_ms_to_utc(c.close_time_ms),
                                  exit_px=lvl, net_pct=net * 100,
                                  r_multiple=net / open_t["stop_dist_frac"],
                                  bars_held=i - open_t["entry_i"],
                                  exit_reason="stop")
                    trades.append(open_t)
                    open_t = None
                    continue
            # track adverse excursion intra-hold (long: lows; short: highs)
            adverse = (c.low / e - 1) if side == "LONG" else (e / c.high - 1) * -1 * -1
            if side == "LONG":
                adverse = c.low / e - 1
            else:
                adverse = (e - c.high) / e
            open_t["mae"] = min(open_t["mae"], adverse)
            held = i - open_t["entry_i"]
            ret = (c.close / e - 1) if side == "LONG" else (e - c.close) / e
            net = ret - 2 * FEE
            if exit_mode == "atr_tp":
                # Harvest the bounce: exit at entry +/- tp_atr_mult x ATR(entry),
                # not the first profitable tick.
                tp_dist = tp_atr_mult * open_t["atr_at_entry"] / e
                rev_hit = ret >= tp_dist
            else:
                rev_hit = net > 0
            fis_hit = (fisher[i] >= REVERSAL_EXIT_LEVEL) if side == "LONG" \
                else (fisher[i] <= -REVERSAL_EXIT_LEVEL)
            cap_hit = cap_bars is not None and held >= cap_bars
            if rev_hit or fis_hit or cap_hit:
                reason = ("both" if (rev_hit and fis_hit)
                          else "reversion" if rev_hit
                          else "fisher_reversal" if fis_hit
                          else "time_cap")
                open_t.update(exit_i=i, exit_ts=_ms_to_utc(c.close_time_ms),
                              exit_px=c.close, net_pct=net * 100,
                              bars_held=held, exit_reason=reason)
                if stop_atr_mult is not None and "stop_dist_frac" in open_t:
                    open_t["r_multiple"] = net / open_t["stop_dist_frac"]
                trades.append(open_t)
                open_t = None
            continue
        # flat: check entry at this close
        f = fisher[i]
        bj = bisect_right(bias_close_ms, c.close_time_ms) - 1
        b = bias_dirs[bj] if bj >= 0 else 0
        side = None
        if f <= -thr and b == 1:
            side = "LONG"
        elif f >= thr and b == -1 and not long_only:
            side = "SHORT"
        if side:
            open_t = {"side": side, "entry_i": i, "entry": c.close,
                      "entry_ts": _ms_to_utc(c.close_time_ms),
                      "fisher_at_entry": round(f, 2), "mae": 0.0,
                      "atr_at_entry": (atr_series[i] if atr_series else 0.0)}
            if stop_atr_mult is not None:
                if not atr_series or atr_series[i] <= 0:
                    raise ValueError("stop_atr_mult requires a valid ATR series")
                open_t["stop_level"] = c.close - stop_atr_mult * atr_series[i]
                open_t["stop_dist_frac"] = stop_atr_mult * atr_series[i] / c.close
    if open_t is not None:
        c = candles_4h[-1]
        e = open_t["entry"]
        ret = (c.close / e - 1) if open_t["side"] == "LONG" else (e - c.close) / e
        open_t.update(exit_i=None, exit_ts="OPEN", exit_px=c.close,
                      net_pct=(ret - 2 * FEE) * 100,
                      bars_held=len(candles_4h) - 1 - open_t["entry_i"],
                      exit_reason="unresolved")
        trades.append(open_t)
    return trades


def run_config_dca(candles_4h, fisher, bias_dirs, bias_close_ms, thr,
                   trigger: str, max_adds: int = 3,
                   div_lookback: int = 10, reversal_delta: float = 0.25) -> list[dict]:
    """Round 6: multi-tranche episodes (Martingale-adjacent — adds increase
    exposure into adversity). Single-entry run_config is left untouched.

    Pre-registered rules:
      deeper     add at each new level thr+0.5*k below entry (-1.75, -2.25, -2.75)
      divergence add on a new local low (trailing div_lookback bars, lower than
                 the last recorded low event) whose Fisher is LESS extreme than
                 at that prior low; the reference low updates on every new low
                 event whether or not it diverges
      reversal   add when Fisher turns up reversal_delta off the episode min;
                 re-arms only after a NEW min below the last add's reference
    Exits evaluated BEFORE adds each bar (no add on the exit bar), on the
    BLENDED position: first-profit = close beats avg entry by round-trip fees
    (per-unit fees are tranche-count invariant); Fisher-reversal at +1.5.
    Equal tranches, fixed % of initial capital each; max_adds bound is a
    technical default, not policy."""
    episodes: list[dict] = []
    ep: dict | None = None
    for i in range(WARMUP_4H, len(candles_4h)):
        c = candles_4h[i]
        if ep is not None:
            k = len(ep["tranches"])
            avg_e = sum(px for _, px in ep["tranches"]) / k
            # full-exposure adverse excursion, in per-tranche-notional units
            adverse_units = sum(c.low / px - 1 for _, px in ep["tranches"])
            ep["mae_units"] = min(ep["mae_units"], adverse_units)
            ep["mae_deployed"] = min(ep["mae_deployed"], adverse_units / k)
            ret = c.close / avg_e - 1
            net = ret - 2 * FEE
            fis_hit = fisher[i] >= REVERSAL_EXIT_LEVEL
            if net > 0 or fis_hit:
                ep.update(exit_ts=_ms_to_utc(c.close_time_ms), exit_px=c.close,
                          avg_entry=avg_e, net_pct=net * 100,
                          pnl_units=k * net * 100,
                          bars_held=i - ep["tranches"][0][0],
                          exit_reason=("reversion" if net > 0 else "fisher_reversal"))
                episodes.append(ep)
                ep = None
                continue
            # add-trigger checks (only while still open, tranches remaining)
            if k < 1 + max_adds:
                add = False
                if trigger == "deeper":
                    next_level = -(thr + 0.5 * k)
                    if fisher[i] <= next_level:
                        add = True
                elif trigger == "divergence":
                    lo = min(x.low for x in candles_4h[i - div_lookback + 1: i + 1])
                    if c.low == lo and c.low < ep["ref_low"]:
                        if fisher[i] > ep["ref_low_fisher"]:
                            add = True
                        ep["ref_low"], ep["ref_low_fisher"] = c.low, fisher[i]
                elif trigger == "reversal":
                    if fisher[i] < ep["ep_min"]:
                        ep["ep_min"] = fisher[i]
                    if (ep["ep_min"] < ep["ref_min"]
                            and fisher[i] >= ep["ep_min"] + reversal_delta):
                        add = True
                        ep["ref_min"] = ep["ep_min"]
                if add:
                    ep["tranches"].append((i, c.close))
                    ep["add_gaps_bars"].append(i - ep["last_tranche_i"])
                    ep["last_tranche_i"] = i
                    ep["add_fishers"].append(round(fisher[i], 2))
            continue
        # flat: base entry identical to the single-entry design
        bj = bisect_right(bias_close_ms, c.close_time_ms) - 1
        b = bias_dirs[bj] if bj >= 0 else 0
        if fisher[i] <= -thr and b == 1:
            ep = {"tranches": [(i, c.close)], "entry_ts": _ms_to_utc(c.close_time_ms),
                  "entry1": c.close, "fisher_at_entry": round(fisher[i], 2),
                  "mae_units": 0.0, "mae_deployed": 0.0,
                  "last_tranche_i": i, "add_gaps_bars": [], "add_fishers": [],
                  "ref_low": c.low, "ref_low_fisher": fisher[i],
                  "ep_min": fisher[i], "ref_min": fisher[i]}
    if ep is not None:
        k = len(ep["tranches"])
        avg_e = sum(px for _, px in ep["tranches"]) / k
        c = candles_4h[-1]
        net = (c.close / avg_e - 1) - 2 * FEE
        ep.update(exit_ts="OPEN", exit_px=c.close, avg_entry=avg_e,
                  net_pct=net * 100, pnl_units=k * net * 100,
                  bars_held=len(candles_4h) - 1 - ep["tranches"][0][0],
                  exit_reason="unresolved")
        episodes.append(ep)
    for ep in episodes:
        ep["k"] = len(ep["tranches"])
        ep["tranches"] = [(i, px) for i, px in ep["tranches"]]
    return episodes


def summarize_dca(episodes: list[dict]) -> dict:
    if not episodes:
        return {"episodes": 0}
    total_units = sum(e["pnl_units"] for e in episodes)          # % of ONE tranche's notional
    ks = [e["k"] for e in episodes]
    multi = [e for e in episodes if e["k"] > 1]
    reverted = sorted(e["bars_held"] / BARS_PER_DAY_4H
                      for e in episodes if e["exit_reason"] == "reversion")
    def pct(v, q):
        return v[min(len(v) - 1, math.ceil(q * len(v)) - 1)] if v else None
    hostages = [e for e in episodes if e["mae_deployed"] * 100 <= -5]
    worst = min(episodes, key=lambda e: e["mae_units"])
    return {
        "episodes": len(episodes),
        "wins": sum(1 for e in episodes if e["pnl_units"] > 0),
        "tranche_distribution": {str(k): ks.count(k) for k in sorted(set(ks))},
        "total_pnl_units": round(total_units, 2),
        "capital_pnl_pct": {f"{s:.0f}%": round(total_units * s / 100, 2) for s in SIZES_PCT},
        "max_concurrent_tranches": max(ks),
        "worst_case_exposure_pct_capital": {f"{s:.0f}%": max(ks) * s for s in SIZES_PCT},
        "avg_entry_improvement_pct": (round(sum((e["entry1"] - e["avg_entry"]) / e["entry1"]
                                                for e in multi) / len(multi) * 100, 3)
                                      if multi else None),
        "worst_mae_units": round(worst["mae_units"] * 100, 2),
        "worst_mae_pct_capital": {f"{s:.0f}%": round(worst["mae_units"] * 100 * s / 100, 2)
                                  for s in SIZES_PCT},
        "worst_mae_deployed_pct": round(min(e["mae_deployed"] for e in episodes) * 100, 2),
        "worst_episode": {kk: worst[kk] for kk in ("entry_ts", "k", "exit_reason", "net_pct", "pnl_units")},
        "ttr_days": ({"median": round(pct(reverted, 0.5), 1), "p90": round(pct(reverted, 0.9), 1),
                      "max": round(reverted[-1], 1)} if reverted else None),
        "exit_reasons": {r: sum(1 for e in episodes if e["exit_reason"] == r)
                         for r in ("reversion", "fisher_reversal", "unresolved")},
        "rescue_dependence_pct": (round(100 * sum(e["pnl_units"] for e in hostages) / total_units, 1)
                                  if total_units != 0 else None),
        "add_gaps_bars_all": [g for e in episodes for g in e["add_gaps_bars"]],
        "mean_tranches": round(sum(ks) / len(ks), 2),
    }


def phase_run_dca(thr: float, tag: str, max_adds: int = 3) -> None:
    candles_4h, _ = load_snapshot("4h")
    fisher = fisher_transform(candles_4h)[0]
    bc, _ = load_snapshot("12h")
    dirs, times = bias_direction_series(bc, 30)   # Round 4 baseline: 12H SMA30
    out = {}
    for trig in ("deeper", "divergence", "reversal"):
        eps = run_config_dca(candles_4h, fisher, dirs, times, thr, trig, max_adds)
        s = summarize_dca(eps)
        out[trig] = {"summary": s, "episodes": eps}
        print(f"\n=== {trig} ===")
        print(json.dumps({k: v for k, v in s.items() if k != "add_gaps_bars_all"}, indent=1))
        if s.get("add_gaps_bars_all"):
            gaps_d = [round(g / BARS_PER_DAY_4H, 1) for g in s["add_gaps_bars_all"]]
            print(f"add gaps (days): {gaps_d}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUTPUT_DIR / f"track4_results_{tag}.json"
    p.write_text(json.dumps(
        {"ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "base": {"thr": thr, "bias": "12h/SMA30", "long_only": True,
                  "exit": "first_profit_blended", "max_adds": max_adds},
         "designs": out}, indent=1), encoding="utf-8")
    print(f"\nwritten: {p}")


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0}
    nets = [t["net_pct"] for t in trades]
    maes = [t["mae"] * 100 for t in trades]
    reverted = [t for t in trades if t["exit_reason"] in ("reversion", "both")]
    holds = sorted(t["bars_held"] / BARS_PER_DAY_4H for t in reverted)
    def pct(sorted_vals, q):
        return sorted_vals[min(len(sorted_vals) - 1, math.ceil(q * len(sorted_vals)) - 1)]
    worst_i = min(range(len(trades)), key=lambda k: maes[k])
    return {
        "trades": len(trades),
        "wins": sum(1 for n in nets if n > 0),
        "sum_net_pct_position": round(sum(nets), 2),
        "capital_pnl_pct": {f"{s:.0f}%": round(sum(nets) * s / 100, 2) for s in SIZES_PCT},
        "exit_reasons": {r: sum(1 for t in trades if t["exit_reason"] == r)
                         for r in ("reversion", "fisher_reversal", "both", "time_cap", "unresolved")},
        "worst_mae_pct_position": round(min(maes), 2),
        "worst_mae_pct_capital": {f"{s:.0f}%": round(min(maes) * s / 100, 2) for s in SIZES_PCT},
        "worst_trade": {k: trades[worst_i][k] for k in
                        ("side", "entry_ts", "exit_ts", "exit_reason", "net_pct")} |
                       {"mae_pct_position": round(maes[worst_i], 2)},
        "time_to_revert_days": (None if not holds else
                                {"median": round(pct(holds, 0.5), 1),
                                 "p90": round(pct(holds, 0.9), 1),
                                 "max": round(holds[-1], 1), "n": len(holds)}),
    }


def phase_run(thresholds: tuple[float, ...] = ENTRY_THRESHOLDS, tag: str = "",
              bias_tfs: tuple[str, ...] = BIAS_TFS,
              exit_modes: tuple[str, ...] = ("first_profit",),
              caps: tuple = HOLD_CAPS_DAYS, long_only: bool = False,
              sma_windows: tuple[int, ...] = SMA_WINDOWS,
              stop_atr_mult: float | None = None) -> None:
    from strategy.atr import wilder_atr
    candles_4h, _ = load_snapshot("4h")
    fisher = fisher_transform(candles_4h)[0]
    atr = wilder_atr(candles_4h)
    # Guard: refuse to run on the buggy Fisher (saturated distribution).
    share_ge2 = sum(1 for v in fisher[20:] if abs(v) >= 2) / (len(fisher) - 20)
    if share_ge2 > 0.05:
        raise RuntimeError("Fisher distribution looks saturated — is the 9da31ee fix applied?")
    # Entry-condition frequency (the "why so few trades" table)
    freq = {f"|F| >= {t}": sum(1 for v in fisher[WARMUP_4H:] if abs(v) >= t)
            for t in thresholds}
    print(f"4H bars {len(candles_4h)} ({_ms_to_utc(candles_4h[0].close_time_ms)} .. "
          f"{_ms_to_utc(candles_4h[-1].close_time_ms)}); entry-condition bar counts: {freq}")

    bias = {}
    for tf in bias_tfs:
        bc, _ = load_snapshot(tf)
        for w in sma_windows:
            bias[(tf, w)] = bias_direction_series(bc, w)

    results = []
    for tf in bias_tfs:
        for w in sma_windows:
            dirs, times = bias[(tf, w)]
            for thr in thresholds:
                for cap in caps:
                    for em in exit_modes:
                        trades = run_config(candles_4h, fisher, dirs, times, thr, cap,
                                            long_only=long_only, exit_mode=em,
                                            atr_series=atr, stop_atr_mult=stop_atr_mult)
                        s = summarize(trades)
                        results.append({"bias_tf": tf, "sma": w, "thr": thr,
                                        "cap_days": cap, "exit_mode": em,
                                        "long_only": long_only,
                                        "summary": s, "trades": trades})
                        cap_s = f"{cap}d" if cap else "none"
                        if s["trades"]:
                            print(f"{tf}/SMA{w} thr={thr} cap={cap_s:>4} {em:>12}: "
                                  f"trades {s['trades']:3d} wins {s['wins']:3d} "
                                  f"| pos P&L {s['sum_net_pct_position']:+8.2f}% "
                                  f"| cap@10% {s['capital_pnl_pct']['10%']:+6.2f}% "
                                  f"| worstMAE(pos) {s['worst_mae_pct_position']:+.2f}% "
                                  f"| exits {s['exit_reasons']}")
                        else:
                            print(f"{tf}/SMA{w} thr={thr} cap={cap_s:>4} {em:>12}: trades 0")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / (f"track4_results_{tag}.json" if tag else "track4_results.json")
    out.write_text(json.dumps(
        {"ran_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "entry_condition_bar_counts": freq, "grid_runs": len(results),
         "results": results}, indent=1), encoding="utf-8")
    print(f"\nwritten: {out} ({len(results)} configs)")


def phase_selfcheck() -> None:
    # Synthetic: price dips (Fisher forced negative), bias UP, then recovers.
    n = 120
    candles = []
    px = 100.0
    for i in range(n):
        px = 100 - 10 * math.sin(min(i, 40) / 40 * math.pi) if i < 40 else px * 1.01
        candles.append(Candle(i * 100, i * 100 + 99, px, px * 1.001, px * 0.999, px, 0.0))
    fisher = [-2.5 if 61 <= i <= 63 else 0.0 for i in range(n)]
    dirs = [1] * n
    times = [c.close_time_ms for c in candles]
    trades = run_config(candles, fisher, dirs, times, 2.0, None)
    # Fisher stays at -2.5 for 3 bars: enter @61, revert @62, re-enter @63 —
    # re-entry after a completed trade is by design (one at a time, not once).
    assert len(trades) == 2, trades
    for t in trades:
        assert t["side"] == "LONG" and t["exit_reason"] in ("reversion", "both")
        assert t["net_pct"] > 0
        assert t["mae"] <= 0  # adverse excursion is never positive
    # Time cap fires when nothing else does.
    fisher_flat = [-2.5 if i == 61 else 0.0 for i in range(n)]
    down = [Candle(i * 100, i * 100 + 99, 100 - i * 0.2, 100 - i * 0.2,
                   100 - i * 0.2 - 0.1, 100 - i * 0.2, 0.0) for i in range(n)]
    trades2 = run_config(down, fisher_flat, [1] * n, [c.close_time_ms for c in down], 2.0, 5)
    assert trades2 and trades2[0]["exit_reason"] == "time_cap"
    assert trades2[0]["net_pct"] < 0 and trades2[0]["mae"] < 0
    # Fisher-reversal exit can fire while unprofitable.
    fisher_rev = [-2.5 if i == 61 else (1.6 if i == 70 else 0.0) for i in range(n)]
    trades3 = run_config(down, fisher_rev, [1] * n, [c.close_time_ms for c in down], 2.0, None)
    assert trades3 and trades3[0]["exit_reason"] == "fisher_reversal" and trades3[0]["net_pct"] < 0
    # ── Track 4-Comp ATR stop ──
    from strategy.atr import wilder_atr
    fisher_stop = [-2.5 if i == 61 else 0.0 for i in range(n)]
    atr_dn = wilder_atr(down)
    t4c = run_config(down, fisher_stop, [1] * n, [c.close_time_ms for c in down],
                     2.0, None, long_only=True, atr_series=atr_dn, stop_atr_mult=1.0)
    assert t4c and t4c[0]["exit_reason"] == "stop", t4c
    assert -2.0 < t4c[0]["r_multiple"] <= -1.0          # ~ -1R minus fees
    assert abs(t4c[0]["exit_px"] - t4c[0]["stop_level"]) < 1e-9  # filled AT the stop
    # stop=None path unchanged (regression: same series, no stop -> time runs on)
    t4n = run_config(down, fisher_stop, [1] * n, [c.close_time_ms for c in down],
                     2.0, None, long_only=True, atr_series=atr_dn)
    assert t4n[0]["exit_reason"] != "stop"

    # ── Round 6 DCA triggers ──
    n2 = 200
    flatpx = [Candle(i * 100, i * 100 + 99, 100, 100.05, 99.95, 100, 0.0) for i in range(n2)]
    times2 = [c.close_time_ms for c in flatpx]
    # deeper: entry at -1.3, adds at -1.8 and -2.3, then blended profit exit
    fD = [0.0] * n2
    fD[70], fD[72], fD[74] = -1.3, -1.8, -2.3
    pxD = list(flatpx)
    for j in range(70, 75):
        p = 100 - (j - 69) * 2.0
        pxD[j] = Candle(j * 100, j * 100 + 99, p, p + 0.05, p - 0.05, p, 0.0)
    for j in range(75, n2):
        pxD[j] = Candle(j * 100, j * 100 + 99, 99, 99.05, 98.95, 99, 0.0)
    epsD = run_config_dca(pxD, fD, [1] * n2, times2, 1.25, "deeper", 3)
    assert len(epsD) == 1 and epsD[0]["k"] == 3, epsD  # entry + 2 adds (-2.75 never reached)
    assert epsD[0]["exit_reason"] == "reversion" and epsD[0]["pnl_units"] > 0
    assert epsD[0]["mae_units"] < 0
    # divergence: lower low with less-extreme fisher -> exactly one add
    fV = [0.0] * n2
    fV[70], fV[80] = -1.4, -1.1
    pxV = list(flatpx)
    pxV[70] = Candle(7000, 7099, 95, 95.05, 94.9, 95, 0.0)
    for j in range(71, 80):
        pxV[j] = Candle(j * 100, j * 100 + 99, 95, 95.2, 94.95, 95, 0.0)
    pxV[80] = Candle(8000, 8099, 94, 94.05, 93.9, 94, 0.0)   # lower low, fisher -1.1 > -1.4
    for j in range(81, n2):
        pxV[j] = Candle(j * 100, j * 100 + 99, 96, 96.05, 95.95, 96, 0.0)
    epsV = run_config_dca(pxV, fV, [1] * n2, times2, 1.25, "divergence", 3)
    assert len(epsV) == 1 and epsV[0]["k"] == 2, epsV
    # reversal: new min below entry, then +0.25 turn -> one add; no re-fire without new min
    fR = [0.0] * n2
    fR[70], fR[71], fR[72], fR[73], fR[74] = -1.3, -1.6, -1.34, -1.33, -1.32
    pxR = list(pxD)
    epsR = run_config_dca(pxR, fR, [1] * n2, times2, 1.25, "reversal", 3)
    assert len(epsR) == 1 and epsR[0]["k"] == 2, epsR
    # blended fee math: per-unit fees are tranche-count invariant
    assert abs(epsD[0]["pnl_units"] - epsD[0]["k"] * epsD[0]["net_pct"]) < 1e-9
    print("selfcheck: all assertions passed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--phase", required=True, choices=("selfcheck", "run", "run-dca"))
    ap.add_argument("--max-adds", type=int, default=3)
    ap.add_argument("--thresholds", default="2.0,3.0",
                    help="entry |Fisher| thresholds, comma-separated (round 1: 2.0,3.0; "
                         "round 2 per Zane's clarified intent: 1.5)")
    ap.add_argument("--tag", default="", help="suffix for the output file (round provenance)")
    ap.add_argument("--bias-tfs", default="1d,12h")
    ap.add_argument("--exit-modes", default="first_profit",
                    help="comma list of {first_profit, atr_tp}")
    ap.add_argument("--caps", default="none,14,30", help="comma list of day caps; 'none' allowed")
    ap.add_argument("--long-only", action="store_true",
                    help="round-3 rule: mean reversion within an UP trend only")
    ap.add_argument("--sma-windows", default="30,50",
                    help="comma list of bias SMA windows (round 4: single window)")
    ap.add_argument("--stop-atr-mult", type=float, default=None,
                    help="Track 4-Comp: ATR stop multiplier (None = no stop, unchanged)")
    args = ap.parse_args()
    if args.phase == "selfcheck":
        phase_selfcheck()
    elif args.phase == "run-dca":
        thr = float(args.thresholds.split(",")[0])
        phase_run_dca(thr, args.tag or "r6_dca", args.max_adds)
    else:
        thresholds = tuple(float(t) for t in args.thresholds.split(","))
        caps = tuple(None if c == "none" else int(c) for c in args.caps.split(","))
        phase_run(thresholds, args.tag,
                  bias_tfs=tuple(args.bias_tfs.split(",")),
                  exit_modes=tuple(args.exit_modes.split(",")),
                  caps=caps, long_only=args.long_only,
                  sma_windows=tuple(int(w) for w in args.sma_windows.split(",")),
                  stop_atr_mult=args.stop_atr_mult)


if __name__ == "__main__":
    main()
