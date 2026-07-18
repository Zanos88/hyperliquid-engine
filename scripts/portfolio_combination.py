"""Portfolio combination: TSMOM30 + Funding MR — combine uncorrelated signals.
Both use regime_labels for clean signal generation. Tests equal-weight and
adaptive blends."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from factor_correlation_study import OUTPUT_DIR, load_snapshot
from strategy_tournament import BARS_PER_YEAR, FEE, WARMUP, log_returns, metrics, net_strategy_returns, eval_bounds

candles, _ = load_snapshot("1d")
rets = log_returns(candles)
bpy = BARS_PER_YEAR["1d"]
closes = [c.close for c in candles]
a, ee, _ = eval_bounds(len(candles))

# ── Load funding component from regime labels ──
regime_path = OUTPUT_DIR / "regime_labels_btc.json"
funding_by_ms = {}
for r in json.loads(regime_path.read_text())["labels"]:
    ms = r["close_ms"]
    fv = r.get("funding")
    if fv is not None:
        funding_by_ms[ms] = fv

# ── Signal generators ──
def funding_mr_positions(cndls):
    pos = [0] * len(cndls)
    for i, c in enumerate(cndls):
        if i < 365:
            continue
        fv = funding_by_ms.get(c.close_time_ms)
        if fv == "BEAR":
            pos[i] = 1
    return pos

def tsmom30_positions(cndls):
    pos = [0] * len(cndls)
    for i in range(len(cndls)):
        if i >= 30 and cndls[i].close > cndls[i - 30].close:
            pos[i] = 1
    return pos

def sma50_positions(cndls):
    pos = [0] * len(cndls)
    for i in range(len(cndls)):
        if i < 50:
            continue
        ma = sum(cndls[j].close for j in range(i - 49, i + 1)) / 50.0
        if cndls[i].close > ma:
            pos[i] = 1
    return pos

# ── Generate all positions ──
pos_tsmom = tsmom30_positions(candles)
pos_fund = funding_mr_positions(candles)
pos_sma50 = sma50_positions(candles)

# ── Evaluate helper ──
def evaluate(pos, rets_vec):
    net = net_strategy_returns(pos, rets_vec)
    m = metrics(net, pos, a, ee, bpy)
    return m, net

# ── Baselines ──
m_ts, net_ts = evaluate(pos_tsmom, rets)
m_fd, net_fd = evaluate(pos_fund, rets)
m_s5, net_s5 = evaluate(pos_sma50, rets)

print("=== BASELINES ===")
for name, m in [("TSMOM30", m_ts), ("Funding MR", m_fd), ("SMA50", m_s5)]:
    print(f"  {name:12s}: Sh={m['sharpe']:.4f}  Ret={m['ann_return_pct']:7.2f}%  "
          f"DD={m['max_dd_log']:.4f}  Trades={m['trades']:3.0f}  "
          f"Exp={m['exposure']*100:.0f}%  Net={m['net_multiple']:.4f}")

# ── Comparison collector ──
results: list[tuple[str, dict]] = []

# ── Equal-weight 50/50 ──
net_5050 = [(nt + nf) / 2 for nt, nf in zip(net_ts, net_fd)]
pos_5050 = [1 if t or f else 0 for t, f in zip(pos_tsmom, pos_fund)]
m_5050 = metrics(net_5050, pos_5050, a, ee, bpy)
results.append(("50/50 TSMOM30 + FundMR", m_5050))
print(f"\n=== EQUAL-WEIGHT 50/50 ===")
print(f"  Sh={m_5050['sharpe']:.4f}  Ret={m_5050['ann_return_pct']:7.2f}%  "
      f"DD={m_5050['max_dd_log']:.4f}  Net={m_5050['net_multiple']:.4f}")

# ── Additive (TSMOM30 at full + FundMR when BEAR) ──
net_add = [nt + nf for nt, nf in zip(net_ts, net_fd)]
pos_add = [1 if t or f else 0 for t, f in zip(pos_tsmom, pos_fund)]
m_add = metrics(net_add, pos_add, a, ee, bpy)
results.append(("Additive TSMOM30+FundMR", m_add))
print(f"\n=== ADDITIVE (TSMOM30 1x + FundMR 1x when BEAR) ===")
print(f"  Sh={m_add['sharpe']:.4f}  Ret={m_add['ann_return_pct']:7.2f}%  "
      f"DD={m_add['max_dd_log']:.4f}  Net={m_add['net_multiple']:.4f}")

# ── Weighted: TSMOM30 full time + weighted FundMR when BEAR ──
for w_fund in [0.25, 0.50, 0.75, 1.0]:
    w_tsmom = 1.0 - w_fund
    net_w = [0.0] * len(rets)
    for i in range(len(rets)):
        if pos_fund[i]:
            net_w[i] = w_tsmom * net_ts[i] + w_fund * net_fd[i]
        else:
            net_w[i] = net_ts[i]
    m_w = metrics(net_w, pos_add, a, ee, bpy)
    label = f"TSMOM30 + {w_fund*100:.0f}% FundMR when BEAR"
    results.append((label, m_w))
    print(f"\n=== {label} ===")
    print(f"  Sh={m_w['sharpe']:.4f}  Ret={m_w['ann_return_pct']:7.2f}%  "
          f"DD={m_w['max_dd_log']:.4f}  Net={m_w['net_multiple']:.4f}")

# ── Triple equal ──
net_triple = [(nt + ns + nf) / 3 for nt, ns, nf in zip(net_ts, net_s5, net_fd)]
pos_triple = [1 if t or s or f else 0 for t, s, f in zip(pos_tsmom, pos_sma50, pos_fund)]
m_triple = metrics(net_triple, pos_triple, a, ee, bpy)
results.append(("33/33/33 Triple", m_triple))
print(f"\n=== TRIPLE EQUAL (33/33/33 TSMOM30/SMA50/FundMR) ===")
print(f"  Sh={m_triple['sharpe']:.4f}  Ret={m_triple['ann_return_pct']:7.2f}%  "
      f"DD={m_triple['max_dd_log']:.4f}  Net={m_triple['net_multiple']:.4f}")

# ── Final comparison table ──
print("\n\n=== COMPARISON TABLE ===")
print(f"  {'Strategy':45s} {'Sharpe':>7s} {'AnnRet%':>8s} {'MaxDD':>8s} {'NetMult':>8s}")
for name, m in [("TSMOM30 (baseline)", m_ts), ("Funding MR (baseline)", m_fd),
                 ("SMA50 (baseline)", m_s5)] + results:
    print(f"  {name:45s} {m['sharpe']:>7.4f} {m['ann_return_pct']:>8.2f} {m['max_dd_log']:>8.4f} {m['net_multiple']:>8.4f}")
