# BTC-PERP Research Program — Full Study Summary

Compiled 2026-07-10, post-Fisher-fix. All figures are real run output from
this repo; **all backtest numbers are SIMULATED** (idealized close/touch
fills, no slippage/funding, taker 0.075%/side, Hyperliquid 5,000-bar
retention per timeframe) and reflect small samples unless stated. This
document supersedes the earlier BTC_PERP_Testing_Summary PDF (whose
figures predate the Fisher fix).

---

## 0. Executive summary

| # | Study | Verdict | Headline |
|---|---|---|---|
| 1 | Fisher bug + fix | **Re-baselined everything** | Recursion gain 1.33 → saturated indicator; \|F\|≥2 on ~45% of bars instead of ~0.1%. Fixed + deployed live. |
| 2 | Round 1 — factor correlation (4 factors, 256 cells) | **Null** (buggy AND corrected) | No cell above chance-calibrated bar; corrected F4 cells ~never fire |
| 3 | Round 2 — confirmatory tests of best cell | **Falsified / vacuous** | 0/3, sign reversed on unseen data; corrected: rule fires n=1/0/0 |
| 4 | Rounds 3–4 — trend tournaments (BTC + 7-asset) | **Null at luck bar; directionally strong** | 21/21 cells beat buy-and-hold w/ ~half drawdown; can't clear family-max luck bar |
| 5 | Live trend engine (4h/1h fib-extension) | **Running dry-run, corrected basis +2.86R** | Corrected backtest: 8 trades, PF 1.43, maxDD 3.72R (was +1.28R/6.77R buggy) |
| 6 | tsmom30 forward test | **Running (paper)** | Inception 2026-07-09; flipped LONG at first corrected close; gate ≥180d & ≥10 flips |
| 7 | Track 2 — counter-trend | **Artifact; barely fires corrected** | 1h path: 0 trades at every threshold; 4h remnant 6 trades, uninformative |
| 8 | Track 3 — Fisher cycle | **Artifact; no viable strategy** | 68–78 "cycles" were saturation; corrected: 1 cycle at exh 2.0 in 2.3y |
| 9 | OI × liquidation Phase 0+1 | **Data mapped; gate uninformative** | Funding history free/hourly/2023+; OI credential-gated; gate binds 2/13 entries, split verdict |
| 10 | Track 4 — mean reversion within trend (3 rounds) | **Robust cell named; thin; no-stop tail priced** | −1.25/first_profit long-only: 17–18 all-win, ~7.5/yr, +6.7–7.6% notional, worst MAE −16.5% |

**Program-level:** no statistically provable edge exists in the candle data
this program can reach (≤5.9y, one asset class, one full cycle). Two things
survived every hostile test: (a) **trend-following as risk management**
(drawdown ~halved vs holding, 21/21 specifications), and (b) the **live
config's corrected backtest** (+2.86R, PF 1.43). The honest promotion
instrument for anything is the paper forward test, and one is running.

---

## 1. Methodology (constant across all studies)

- **Pre-registration**: protocol/constants committed BEFORE results exist
  (commit hashes cited in each doc); mechanical selection criteria; one-shot
  write-once holdouts, no `--force`.
- **Multiplicity honesty**: family-max circular-shift "luck bars" (the 95th
  pct of the best cell in shuffled data), exceedance counts vs chance,
  Newey–West t-stats (lag N−1) for overlapping horizons.
- **Frozen inputs**: candle/funding snapshots committed before runs; splits
  stored inside snapshots so holdout boundaries cannot drift.
- **All cells reported**, nulls included; failures published with the same
  prominence as positives. No fabricated numbers anywhere.

Infrastructure built along the way: staging Supabase for DB tests
(`TEST_DATABASE_URL`, live-ref guard), frozen BTC 1H/4H/12H/1D + 6 alt-coin
1D snapshots, hourly funding history (27,142 rows, 2023-05→present), ~15
research scripts, 213-test suite, dry-run forward-test infrastructure.

---

## 2. The Fisher bug (found 2026-07-10 via live Telegram, fixed `9da31ee`)

`strategy/trigger_1h.py` applied Ehlers' ×2 scaling twice → smoothing
recursion gain 0.66+0.67 = **1.33 > 1**: x pegged at the ±0.999 clamp in any
sustained move; Fisher saturated toward its recursive ceiling (~7.6 — the
formula, like TradingView's, includes `+0.5·fisher[t−1]`). Live symptom:
1H Fisher 5.23 vs TV ~3.09. Present since the original implementation
(`5a734f4`, 2026-07-07) → predated every Fisher consumer.

**Measured on frozen data (pinned as regression tests, fail 3/5 on buggy):**

| Series | Version | max \|F\| | p99 | \|F\|≥2 | \|F\|≥3 |
|---|---|---|---|---|---|
| BTC 1H | buggy | 7.60 | 7.57 | 43.1% | 31.9% |
| BTC 1H | corrected | 2.04 | 1.71 | 0.0% | 0.0% |
| BTC 4H | buggy | 7.60 | 7.59 | 46.6% | 35.1% |
| BTC 4H | corrected | 2.21 | 1.78 | 0.2% | 0.0% |

Corrected 4H frequency ladder (drives all threshold design): ≥1.0 → 29.2%
(1,442 bars); ≥1.25 → 14.7% (727); ≥1.5 → 6.0% (296); ≥1.75 → 1.3% (63);
≥2.0 → 0.2% (8); ≥3.0 → never. Matches Zane's real-world observation
("rarely crosses 2–3") exactly.

**Deployed to the live engine 2026-07-10 ~06:47 UTC** (clean boot, DRY-RUN
intact, live 1H Fisher +1.50, regime alert NEUTRAL→BULLISH on first
corrected cycle). Live Fisher readings are trustworthy from that moment;
earlier live signal history is tainted. A secondary display bug (report pos
column showing stale pre-flip position) was fixed the same day; the
"11:28/11:29 nondeterminism" was two code versions, not a data bug.

Full blast-radius report: `docs/FISHER_FIX_REVERIFICATION.md`. Everything
below shows corrected numbers unless labeled buggy.

---

## 3. Round 1 — Factor-correlation study (`docs/FACTOR_CORRELATION_STUDY.md`)

**Question:** do 4 confluence factors (F1 close-position-in-S/R-range, F2
Fisher−R-line gap, F3 ATR-normalized Ichimoku cloud distance, F4 raw Fisher)
predict 4–12-bar (1H) / 2–6-bar (4H) forward returns? 5,000-bar frozen 1H +
4H snapshots, 70/30 chronological split with N-bar purge, 64 pre-registered
boolean cells per panel (8 singles + 24 pairs + 32 triples), NW t-stats,
shift calibration. Prereg `0f21aac`.

**Result: NULL, twice.** Buggy run: exceedance counts 3/2/0/1 vs ~2.9
expected by chance; best cell +2.59 t_NW vs calibration bar 3.64 (a cell
that good appears in ~half of shuffled datasets). Corrected re-run:
quieter still — 0/1/0/0 exceedances, bars 2.56–3.35, no candidate; the F4
"extended" cells now essentially never fire (as a correct rare-extreme
shouldn't). No factor correlation exceeded ~1.4 rough SE; no quintile
gradient was monotone. Holdouts were never contaminated by round 1.

Notable secondary observation (post-hoc, never promoted): returns
concentrated when factors were *neutral*, not extreme.

---

## 4. Round 2 — Confirmatory tests (`docs/FACTOR_CONFIRMATORY_TESTS.md`)

Round 1's best-looking cell ("washed-out dip near support": F4≤−2 ∧ F2<0 ∧
F1≤0.25, long, N=4) tested one-shot on three windows. Prereg `1b8348c`.

**Result: 0/3 FAIL — decisive.** (buggy factors) Test 0, same-TF unseen 1H
holdout: n=56, mean −0.25%, t_NW **−1.94** — full sign reversal of the
+2.59 discovery. Test 1 (4H holdout): −0.31%, t −0.81. Test 2 (12H, 4.4y):
−0.20% vs a positive baseline. 11/12 phase subsamples negative.
**Corrected re-run: the rule is vacuous** — fires n=1/0/0 (F4≤−2 barely
exists). The textbook exploration-artifact demonstration; the calibration
bar had been right to reject it.

---

## 5. Rounds 3–4 — Trend tournaments (`docs/STRATEGY_TOURNAMENT.md`)

Seven classic variants (SMA50/100/200 long/flat, Donchian 20/10 & 55/20,
TSMOM 30/90), fees included, no tuning. Round 3: BTC 1D (2020-08→2026-07,
two full cycles) + 12H. Round 4: equal-weight across BTC/ETH/SOL/DOGE/XRP/
AVAX/LINK 1D (all ≥2,100 gap-free bars). 70/30 splits; family-max shift
luck bars; prereg `08b1853` / `e6b9028`. (Fisher-free — unaffected by the
bug.)

| Panel | Buy-and-hold | Best variant | Luck bar | Verdict |
|---|---|---|---|---|
| BTC 1D | ×1.89, Sharpe 0.28, maxDD 1.46 | tsmom30 ×3.03, +34.5%/yr, Sharpe 0.77, maxDD 0.63 | 1.40 | below bar |
| BTC 12H | ×2.00, 0.44, 0.99 | sma200 ×2.65, +38.9%/yr, 0.91, 0.51 | 1.59 | below bar |
| 7-asset EW | ×2.09, 0.25, 1.82 | tsmom30 ×3.99, +45.8%/yr, 0.78, 0.74 | 2.05 | below bar |

**Verdict: null at the bar, but a power failure, not a falsification** —
**21 of 21 trend cells beat buy-and-hold risk-adjusted with roughly half
the drawdown**, replicating the external literature (the Sharpe comes from
sidestepping the 2021-22 −77% bear). Breadth didn't buy power because
crypto sleeves are ~1.5 effective independent bets. Holdouts (1D
2024-12→2026-07; 12H 2025-03→; breadth 2024-12→) remain **unburned** — one
future pre-registered confirmation each. Surviving claim: **trend as risk
management**, not provable alpha.

---

## 6. Live systems (both running now)

### 6.1 Live trend engine — 4h/1h, structural stop, fib-extension target
Railway worker, dry-run (both arming switches closed), corrected Fisher
since 2026-07-10. Floors: static $94,000, daily = day-start −$3,000,
circuit breaker −2.5% daily, DB floor-guard trigger as last defense.

**Corrected backtest basis** (`docs/CORRECTED_BASELINE_4H1H.md`, 209 days):
**8 trades, 4-4, +2.86R, PF 1.43, maxDD 3.72R** (buggy basis was 9 trades,
+1.28R, PF 1.15, maxDD 6.77R; exact reconciliation: the fix dropped two
artifact losers, added one genuine loser). Trades resolve fast (6/8 within
2 bars); losses capped −1.5 to −2R; ~14 trades/yr pace. 1d/4h corrected:
0-4, −5.52R — remains negative; 4h/1h stays the only live-worthy pair.

### 6.2 Trend forward test — tsmom30 / sma50 / buy_hold (paper, $100k each)
`forward_test.py`, inception 2026-07-09, BTC 1D, fee 0.075%/side, marks in
`trend_forward_marks` only (never portfolio_telemetry — floor-guard reads
it unfiltered). Windows scheduled task (10:30/20:30/logon), idempotent,
self-healing ~270 days. Audible flip alerts; silent per-tick report table.
First real event: **tsmom30 flipped LONG at the 2026-07-09 close** (30-day
momentum turned positive). **Review gate: ≥180 days AND ≥10 tsmom30 flips;
criteria: net > 0 and Sharpe ≥ buy_hold on the same marks.** No early
decisions.

---

## 7. Track 2 — Ichimoku counter-trend (`docs/TRACK2_ICHIMOKU_MEAN_REVERSION.md`)

Backtest-only 4h/1h mean-reversion module. Original (buggy) result: 9–26
trades with an intriguing fisher-1h-positive / fisher-4h-negative split.
**Corrected: the split was an artifact** — the 1h Fisher path fires **zero
trades at every threshold**; the 4h lrs_flattening@1.5 remnant is 6 trades,
3-3, +0.84R (PF 4.02) — tiny-n, uninformative. Premise barely triggers
under a correct indicator.

---

## 8. Track 3 — Fisher cycle (`docs/TRACK3_FISHER_CYCLE.md`)

1D bias + 4H Fisher exhaustion cycling, backtest-only. Original (buggy):
68–78 cycles, "well-sampled null" (best cell +1.58R, PF 1.03). **Corrected:
the sample was saturation artifact** — at exhaustion 2.0: **1 cycle in 2.3
years**; at 2.5: zero; at 1.5: 13 cycles losing heavily (−12.8/−18.3R, win
rate 5–12%). **No viable strategy**; any future Fisher-threshold design
must start from the corrected event frequencies.

---

## 9. OI × Liquidation — Phase 0 + 1 (`docs/OI_LIQUIDATION_PHASE0_PHASE1.md`)

**Phase 0 (data reality, verified):** funding history official/free/hourly
from 2023-05-12 (frozen, 27,142 rows). OI history exists in Hyperliquid's
S3 archive but is requester-pays (anonymous 403) — needs AWS creds or a
free Coinalyze/Pinax key; **OI conjunction coded but dormant** until a
credential is supplied. 0xArchive liquidation events: **Dec 2025+ (~7
months)**; its Apr-2023 depth is order-books/fills, not liquidations.

**Phase 1 (trend-exhaustion stand-down gate, funding-only):** suppress
crowded-direction entries at trailing-30d funding percentile extremes,
wired exactly like the V2.2 Fisher-4H filter. On corrected baselines: the
gate binds on 1–2 of the trend system's entries per pair; 4h/1h it removed
a +1.96R winner (−1.96R delta); 1d/4h it removed two losers (+2.85R delta).
**Attribution anecdotes at n=1–2 — strictly uninformative; do not adopt.**
Structural insight: confluence entries fire at mid-range funding; crowding
extremes arrive after trends establish — wrong consumer for the signal.
The fuel-check stack's real home is **Phase 2 cascade-fade event selection
(parked; needs 0xArchive account + event-driven replay backtester + your
separate approval)**. Compliance flag stands: nothing HFT-adjacent, ever,
on the challenge.

---

## 10. Track 4 — Mean reversion WITHIN the trend (`docs/TRACK4_UNCONSTRAINED_MEAN_REVERSION.md`)

Zane's design: LTF (4H) selloff to a Fisher extreme inside an intact HTF
uptrend → long → exit on first profit ("rinse and repeat"). No stop (spot
capital, explicitly NOT challenge-relevant), fixed % of initial capital,
MAE reported with equal weight to P&L. Three rounds, 2024-03→2026-07:

**Round 1 (thr −2.0/−3.0, both sides): VACUOUS — 0 trades in 24 configs.**
Only 8 bars in 2.3y reach \|F\|≥2, and all 8 had every bias definition
aligned WITH the Fisher direction. **Structural finding: 4H Fisher extremes
are trend events, not counter-trend events** — confirmed by Zane's own
intuition, and the reason ±2/±3 entries cannot exist.

**Round 2 (thr −1.5, both sides): the mechanism works.** 20–37 trades per
config; median revert 0.3 days (~2 bars), p90 ~5d, max 11.8d. Best cell
12h/SMA50: 31/31 wins, +18.6% of position notional. But: win rate is ~100%
BY CONSTRUCTION; the real information is the tail — worst trade sat
**−15.3% underwater for 16 days** and realized −8.82% (≈25 average wins);
4–5 hostage trades per config rescued at ~breakeven; hold caps strictly
harmful (14d turns the deep trade into a −12.5% realized loss; 30d ≡ none).
Most of round 2's volume/P&L was the SHORT side.

**Round 3 (long-only, 12H bias, volume + exit axes — Zane's rules):**

| Thr | Exit | SMA30 | SMA50 |
|---|---|---|---|
| −1.0 | first_profit | 47 trades, **+12.23%**, MAE −16.6% | 49 trades, **−48.75%**, MAE −34.2% |
| **−1.25** | **first_profit** | **17, +6.66%, −16.5%** | **18, +7.64%, −16.5%** |
| −1.5 | first_profit | 6, +4.50%, −3.7% | 9, +7.31%, −3.7% |

- **The −1.0 volume cell is a trap**: 21 trades/yr, but twin bias configs
  differ by 61 points — survival hinges on SMA-lag luck at regime turns.
- **ATR take-profit rejected by evidence** (worse in 3/4 comparisons); the
  quick first-profit escape is the strategy's working half.
- **The robust cell: long-only, 4H Fisher ≤ −1.25 in a 12H-SMA uptrend,
  first-profit exit** — positive on both SMA windows, all-win, ~7.5
  trades/yr, worst MAE −16.5% of position, unbounded tail by design.
  Economics: ~+3%/yr on deployed notional → **~0.15–0.3%/yr of capital at
  survivable 5–10% sizing**. Positive expectancy on this window is a
  regime property (every 2024-26 dip bounced), not a strategy property.

**Promotion path:** paper forward test of the named cell (same instrument
as tsmom30) — the only honest next step after three sequential rounds on
one window.

---

## 11. Cross-cutting conclusions

1. **No provable edge in reachable candle data.** Four pre-registered
   rounds + four tracks; every null stayed null through the Fisher
   correction, and the one "discovery" that looked real (round 1's +2.59
   cell) reversed sign out-of-sample — the program's guardrails worked.
2. **What survived:** trend-as-risk-management (21/21 cells, ~half the
   drawdown of holding); the live config's corrected basis (+2.86R, PF
   1.43); Track 4's robust-but-thin −1.25 reversion cell.
3. **Structural market facts established:** corrected 4H Fisher reaches
   ±2 four bars/year and ±3 never; Fisher extremes co-occur WITH the
   higher-TF trend; within-trend dips revert in hours (median 0.3d) but
   occasionally hold you hostage 10–16% underwater for weeks; parameter-
   neighborhood stability is the minimum bar for believing any cell
   (the −1.0 trap: +12% vs −49% on adjacent configs).
4. **Frequency reality:** nothing in the Fisher/trend families exceeds
   ~20 trades/yr without buying catastrophic tail or parameter roulette.
   Genuinely higher frequency requires different data: the parked
   OI/liquidation Phase 2 (event-driven cascades) is the structural path.
5. **Process lessons banked:** pre-registration + luck bars prevented two
   would-be false positives; a single-coefficient indicator bug silently
   corrupted five studies for three days — caught by comparing live output
   against theoretical bounds and an independent platform (TradingView).

## 12. Open decisions (all Zane's)

| Decision | Unlocks | Cost |
|---|---|---|
| Wire Track 4's −1.25 cell into the paper forward test | Real out-of-sample evidence for the reversion strategy | Code addition to running forward test (zero capital risk) |
| 0xArchive account | OI/liquidation Phase 2 (cascade-fade — the higher-frequency path) | Account + pricing TBD + separate build approval |
| AWS/Coinalyze/Pinax credential | Funding∧OI conjunction re-run (Phase 1 completeness) | ~free; expect n≤2, low value until Phase 2 |
| Gold 2-Step ($899, 8% trailing / 5% daily) | Bigger risk envelope; R-results unchanged, sizing headroom ~doubles | Floor constants re-parameterization (schema trigger, telemetry, guardian, gate) — analysis on hold per your instruction |
| Forward-test review gates | tsmom30 promotion decision | Time: ≥180d & ≥10 flips (from 2026-07-09) |

*Everything committed on `master` (through `d09ddc4`), suite 213 passed,
no push. Every study has its own doc with full tables; machine-readable
outputs under `research/output/`.*
