# Fisher Fix & Re-verification — 2026-07-10

Fix commit: `9da31ee`. Source brief: FISHER_BUG_AND_REVERIFICATION.md (Zane).
All numbers below are real run output (SIMULATED caveats apply to every
backtest: idealized fills, no slippage/funding, taker 0.075%/side).

## Bug 1 — report position "nondeterminism": explained, not a data bug

The 11:28 vs 11:29 `--report` discrepancy was two code versions, not
nondeterminism: the display fix for the pos column (show CURRENT position,
not position-held-into-bar) landed between the two runs (commit `ad6a5cc`,
2026-07-10 11:29:26 — the two Telegram posts bracket the edit).
`report_text` is a pure function of DB state. **Added:** staging-gated
regression test (`tests/test_forward_report.py`) — identical DB state must
yield identical output, and the pos column must reflect the post-flip
stance. Passing.

## Bug 2 — Fisher out of range: root cause (both prior hypotheses disconfirmed)

`strategy/trigger_1h.py` applied Ehlers' ×2 scaling **twice** (`0.33 * 2 *
raw` with `raw` already spanning ±1), giving the smoothing recursion gain
0.66 + 0.67 = **1.33 > 1** — an unstable filter that pegged x at the ±0.999
clamp in any sustained move and saturated Fisher toward its recursive
ceiling. The clamp itself was correctly placed on the combined running
value, and the ~3.8 ceiling premise was wrong for this (and TradingView's)
formula — both include `+ 0.5·fisher[t−1]`, so the true ceiling is ~7.6,
which is why 5.23 was observable. Fix: `x = 0.33 * raw + 0.67 * x_prev`.

**Real-data measurement (frozen snapshots, deterministic — also pinned as
regression tests, which fail 3/5 on the buggy coefficient):**

| Series | Version | max \|F\| | p99 | \|F\|≥2 | \|F\|≥3 |
|---|---|---|---|---|---|
| BTC 1H (5,002 bars) | buggy | 7.60 | 7.57 | 43.1% | 31.9% |
| BTC 1H | **corrected** | **2.04** | 1.71 | 0.0% | 0.0% |
| BTC 4H (5,000 bars) | buggy | 7.60 | 7.59 | 46.6% | 35.1% |
| BTC 4H | **corrected** | **2.21** | 1.78 | 0.2% | 0.0% |

The corrected distribution matches real-world Fisher behavior (Zane:
"rarely crosses 2–3, never 4–5") — sanity gate passed. Under the bug,
"extended" (±2.0) was true on ~45% of bars: every threshold consumer was
semantically broken.

## Step 3 — the bug predates everything

`trigger_1h.py` was implemented with the doubled ×2 in `5a734f4`
(2026-07-07) and never modified since. Every Fisher consumer — V2.2/V2.3
trend backtests, Track 2, Track 3 (`f9c3d7a`), rounds 1–2 factor studies
(freeze `d115264`), OI Phase 1's trade set, and the live engine's entire
forward-test history — ran on corrupted values.

**Unaffected (no Fisher dependency):** rounds 3–4 trend/breadth
tournaments, the tsmom30/sma50 forward test, OBV, bias/S-R, ATR, Ichimoku.

## Step 4 — staged re-verification results

| Item | Status | Old (buggy) | Corrected |
|---|---|---|---|
| **Live engine** | **FIX NOT YET DEPLOYED — blocked on user** (production deploy requires explicit user action: `railway up --service btc-signal-bot`; restarts the worker, in-memory paper day resets) | 1H Fisher 5.23 on the 14:24 heartbeat | Expected post-deploy 1H Fisher ≈ +1.50 (computed locally on current candles) |
| **Track 3 fisher-cycle** | RE-RUN (`01KX5AF5EA1VYRSTF68KQTV465`) | 68–78 cycles, best cell +1.58R PF 1.03 — "well-sampled null" | exh 2.0: **1 cycle** in 2.3y; exh 2.5: **0**; exh 1.5: 13 cycles, −12.8/−18.3R, wr 5–12%. The old sample was saturation artifact; the premise barely fires at Zane's threshold and loses where it fires. Superseded verdict: **no viable strategy**. ATR-extension follow-up: moot at n≤1. |
| **Round 1 factor study** | RE-RUN (same frozen snapshots; originals archived `research/output/pre_fisher_fix/`) | Null (no cell above calibration bar) | **Null again, quieter**: exceedances 0/1/0/0 vs ~2.9 expected; bars 2.56–3.55; F4-extreme cells now fire ~never (as a correct rare-extreme should). No candidate. |
| **Round 2 confirmatory** | RE-RUN (originals archived) | 0/3 FAIL, sign reversed | 0/3 FAIL trivially: the rule fires **n=1/0/0** — under corrected Fisher the F4≤−2 rule effectively never exists. Original falsification stands, superseded by "rule vacuous". |
| **Track 2 counter-trend** | RE-RUN (`01KX5AM90WPJET2S19VK2QDAGN`) | 9–26 trades; fisher-1h mixed positive vs fisher-4h negative split | The split WAS an artifact: fisher-1h path now fires **zero trades** at every threshold; 4h lrs_flattening@1.5 = 6 trades, 3-3, +0.84R (others 0–1 trades). Premise barely triggers; tiny-n remnant uninformative. |
| **V2.2 Grid B (fisher filter)** | DEFERRED per brief (already concluded negative; the filter's trigger condition now ~never fires, so the conclusion can only move toward "inert") | — | — |
| **V2.3 Grid C headline (4h/1h structural + fib_ext)** | CORRECTED VIA GRID D BASELINE (full Grid C re-run flagged as follow-up) | 9 trades, 4-5, **+1.28R**, PF 1.15, maxDD 6.77 | **8 trades, 4-4, +2.86R, PF 1.43, maxDD 3.72** (`01KX5ANYYXR0CP14EGP9ZWC1XZ`) — the live config's backtest basis *improves* with meaningful Fisher crosses. |
| **OI Phase 1 stand-down gate** | RE-RUN (same sweep file, corrected baselines) | 2/13 suppressions, split 1-1, −0.50R | 4h/1h: gate −1.96R (suppresses a winner again); 1d/4h: gate **+2.85R** (suppresses 2 of 4 losers, −5.52→−2.67). Still n=1–2 per pair: attribution anecdotes, verdict unchanged (**uninformative; do not adopt**). |

## Program-level takeaways

1. The four-round research program's conclusions **survive the fix**: every
   null stays null (mostly more decisively), and no falsified result flips
   positive. The one number that moved favorably is the live config's own
   backtest (+1.28R → +2.86R, PF 1.43, drawdown nearly halved).
2. Track 3 and Track 2's apparent "samples" were largely bug artifacts —
   saturated Fisher generated 5–10× more threshold events than a correct
   indicator does. Any future Fisher-threshold strategy design should start
   from the corrected event frequencies (|F|≥2 ≈ 0–0.2% of bars).
3. The live engine remains the open item: **the fix is committed but not
   deployed** (production deploy withheld for explicit user action). Until
   deployed, live Fisher readings/heartbeats remain saturated and
   cross/no-cross reads are untrustworthy.
