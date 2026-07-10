# Feedback Review · Gold 2-Step Drawdown Envelope · Grid E (Higher Frequency)

Date: 2026-07-10 (post-Fisher-fix deploy). Three deliverables in one doc, per
Zane's instruction. All backtest figures SIMULATED (idealized fills, no
slippage/funding, taker 0.075%/side, retention-limited windows).

## 1. Review of Fable's "BTC-PERP Testing Summary" (uploaded PDF)

The summary is an accurate, honestly-caveated snapshot — **of the pre-fix
world**. It is dated 2026-07-10 but was written before the Fisher fix
(`9da31ee`, deployed 06:47 UTC), and most of its results claims are
superseded by the same-day re-verification:

| PDF claim | Verdict | Corrected state |
|---|---|---|
| Live backtest "9 trades +1.28R, PF 1.15, wr 44%" | **Superseded** | 8 trades, 4-4, **+2.86R, PF 1.43, maxDD 3.72R** (docs/CORRECTED_BASELINE_4H1H.md) |
| "Bias currently NEUTRAL — no trade fired since go-live" | **Stale** | First post-fix evaluation flipped NEUTRAL→BULLISH (06:47 UTC); pre-fix live signal history is void anyway — saturated Fisher gated entries wrongly |
| "hybrid@1.0: 2 trades +4.49R, n too small" | **Superseded (vintage)** | Buggy-Fisher number; un-re-run (Grid B/C full re-runs remain flagged follow-ups) |
| "15m/5m and 1d/4h fib-extension negative" | **Re-answered** | 1d/4h still negative corrected (−5.52R). 15m/5m re-tested in Grid E below — still negative AND still near-zero frequency |
| Track 3 "well-sampled null (68–78 cycles)" | **Superseded** | The sample was a saturation artifact: 1 cycle at exh 2.0, 0 at 2.5; 13 catastrophic cycles at 1.5 (FISHER_FIX_REVERIFICATION.md) |
| Factor study "best cell t=2.59 below calibration bar" | **Superseded** | Rule is vacuous under corrected Fisher (fires n=0); null stands, more decisively |
| Track 2 "lrs_flattening thin positive" | **Superseded** | The fisher-1h/4h split was an artifact; 1h path fires zero trades corrected; 4h lrs@1.5 = 6 trades +0.84R (uninformative n) |
| Trend-forward section (tsmom30/sma50/buy_hold, luck-bar framing, "1.5 independent bets") | **Accurate** | Fisher-independent; unaffected. Forward test running, marks current |
| Parked list (OI Phase 2, carry, longer history, neutral-factor lead) | **Accurate** | Unchanged |
| Floors "static $94,000, daily −$3,000, breaker −2.5%" | **Accurate description of code** | And exactly what §2 shows must change for the Gold 2-Step |

**Net read:** nothing in the PDF was wrong when written; it now needs a
one-line addendum ("all backtest figures pre-date the 2026-07-10 Fisher fix
— see FISHER_FIX_REVERIFICATION.md") if it circulates further.

## 2. Gold 2-Step drawdown envelope (screenshot: 8% TRAILING max DD, 5% daily; vs current 6% static @ $94k, 3% daily)

**What expanded limits do to the backtested results: nothing.** Backtests
produce R-multiples; no backtest path halts on equity floors (floor-guard,
circuit breaker, and guardian floors are live-engine constructs). The
limits change the **R→$ envelope** — sizing headroom and survival math —
computed here from the corrected 4h/1h trade path (8 trades, cum-R path
−1.49 → +3.57 peak → −0.15 trough → +2.86; maxDD-from-HWM 3.72R;
worst from-start dip 1.49R; worst single trade −1.99R):

| Risk/trade | maxDD from HWM | vs 8% trailing (2-Step) | Worst from-start | vs 6% static (current) | Worst day (≈worst trade) | vs 5% / 3% daily |
|---|---|---|---|---|---|---|
| 0.50% | 1.86% | 4.3× headroom | 0.75% | 8.0× | −1.00% | 5.0× / 3.0× |
| 0.75% (live) | 2.79% | 2.9× | 1.12% | 5.4× | −1.49% | 3.4× / 2.0× |
| 1.00% (cap) | 3.72% | 2.2× | 1.49% | 4.0× | −1.99% | 2.5× / 1.5× |

Adverse case (corrected 1d/4h: 4 straight losers, −5.52R): 5.52% at 1% risk
— inside 8% trailing, barely inside 6% static. **Two correlated sleeves at
1% could sum past both budgets** — sizing must treat sleeves jointly.

Three non-obvious points:

1. **Trailing is not uniformly looser.** At the start the 2-Step floor
   (92,000) sits below the current static 94,000 — more room. But it
   ratchets with the high-water mark and **crosses above the static floor
   once HWM > $102,170** (94,000/0.92). On the corrected path the HWM
   reached +3.57% → trailing floor $95,280, i.e. TIGHTER than today's
   assumption exactly when the system is winning. Late-challenge risk must
   shrink to protect banked gains — a behavior nothing in the current
   stack implements.
2. **Internal limits bind first today.** The engine's own circuit breaker
   (−2.5%/day, hard-coded) is tighter than both 3% and 5% daily limits,
   and `risk_params` caps risk_pct at 1%. Buying the bigger challenge
   changes nothing until the internals are retuned.
3. **Code implications (flagged, NOT built):** the 6%/3% assumptions are
   hardcoded in four places — the `schema.sql` floor-guard trigger
   (`GREATEST(day_start−3000, 94000)+200`), `db/store.record_telemetry`
   floor-distance columns, `guardian.py` soft/hard floors, and the
   pre-trade gate clearance — and **nothing tracks a high-water mark**,
   which a trailing floor requires. Adopting the Gold 2-Step needs a
   parameterization pass (floors → config + HWM tracker in Postgres +
   trigger/guardian/gate updates + tests + runbook): roughly a half-day
   build, user-gated, priced here but not executed.
4. **The real constraint the 2-Step adds is the profit target, not the
   drawdown.** 10% then 5% phases: at the corrected single-sleeve pace
   (~+5R/yr ⇒ ~+3.75%/yr at 0.75% risk) the current system is an order of
   magnitude too slow. The drawdown budget is not the binding scarcity —
   trade frequency is. Which is §3.

## 3. Grid E — higher frequency via faster timeframes: NO (and why)

Pre-registered 4-run sweep (`sweep_fast_tf.yaml`, sweep
`01KX5NVPSV6T5N103SP5CND7F4`), corrected Fisher, first honest fast-TF
measurement (the V2.2/V2.3 fast cells were generated by the saturated
indicator):

| Pair | Window | Target | Trades | W-L | Net R | supp_rr | Frequency |
|---|---|---|---|---|---|---|---|
| 15m/5m | ~17 days | nearest | 0 | — | 0.00 | 95 | 0/week |
| 15m/5m | ~17 days | fib_ext | 2 | 0-2 | −3.18 | 92 | **0.8/week** |
| 1h/15m | ~52 days | nearest | 0 | — | 0.00 | 101 | 0/week |
| 1h/15m | ~52 days | fib_ext | 5 | 1-4 | −3.83 | 95 | **0.7/week** |

Pre-registered success bar (≥2–3 gate-passing trades/week, non-catastrophic
R): **FAIL on both counts.** The diagnostic is in the suppression column:
92–101 candidates per window died at the R:R ≥ 2 gate. **The frequency
bottleneck is the R:R gate against structural targets, not the timeframe**
— dropping TF adds fee-bleed losers, not throughput. (Same conclusion V2.2
reached from the stops side; now confirmed with a working Fisher.)

**Where higher frequency can honestly come from, in order of preference:**

1. **Breadth, not speed (recommended next):** run the corrected 4h/1h
   system as parallel sleeves on the liquid universe (ETH/SOL/DOGE/XRP/
   AVAX/LINK — rounds 3/4 already verified deep gap-free history). Seven
   sleeves × ~14 trades/yr ≈ **2/week aggregate** without touching the
   R:R gate, and §2 shows the 2-Step budget fits ~2 sleeves at current
   sizing (correlation-adjusted; joint-DD sizing required). Pre-registered
   multi-asset sweep = one yaml + small harness change (backtest is
   BTC-hardcoded in fetch calls) — cheap build.
2. **R:R-gate sensitivity study (pre-registered, NOT tuning-by-default):**
   one sweep axis gate ∈ {2.0 (live), 1.75, 1.5} on 4h/1h corrected — the
   90-ish suppressed entries per window are a large reservoir; the
   question is whether the marginal entries below 2.0 have positive
   expectancy. This touches the system's core safety trade-off — results
   inform, user decides.
3. **OI Phase 2 cascade-fade** (event-driven, structurally high-frequency)
   — parked; requires 0xArchive account (user decision + spend).

## Reproduce

```powershell
railway run --service btc-signal-bot python backtest.py --sweep sweep_fast_tf.yaml
# envelope numbers derive from stored sweeps 01KX5ANYYXR0CP14EGP9ZWC1XZ (Grid D corrected)
```
