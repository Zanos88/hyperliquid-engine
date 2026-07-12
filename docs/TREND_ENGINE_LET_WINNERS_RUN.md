# Trend Engine — Let-Winners-Run Exits × Long-Only vs Both

Run 2026-07-12. Spot-capital accumulation framing, **NOT the Propr/comp
account**. Brief: `TREND_ENGINE_LET_WINNERS_RUN.md`. Machine-readable (full
per-trade tables + three-way reconciliation): `research/output/trend_let_winners_run.json`.

> **SIMULATED — not live, not comp.** Idealized touch/close fills, no slippage/
> funding, taker 0.075%/side. Frozen 4H/1H BTC snapshots, window **2025-12-12 →
> 2026-07-09** (~209 days). Fixed entries = the same 8 the +2.86R baseline
> produced (`docs/CORRECTED_BASELINE_4H1H.md`), reused unchanged. **Five exit
> models × six scenarios (long-only / short-only / both × single / concurrent)
> = 30 runs, all reported. Combinations DEFERRED** — chosen from these
> individual results only, with a separate go-ahead.

## Read this first — two facts that frame everything

1. **Long-only is n = 1; the short side (n = 7) is the actual test.** The 8
   entries are **7 SHORT + 1 LONG**. The two long-only scenarios contain exactly
   one trade (the 2026-05-24 long) — **descriptive only, no verdict possible on
   the long side in this window.** The brief's premise — "test the long side free
   of the short-side luck that inflated the last result" — *cannot be answered
   here*: this 209-day window barely has a long side (the 1H 5,000-bar retention
   caps how far back longs could be found; see "Scoping a long-side sample"
   below). Consequently **both-directions was already ≈ a short-side test (7 of
   8 trades)**; the short-only cut isolates it cleanly at n=7 and tells the same
   story with the one long removed.

2. **Concurrency never triggered.** The maximum hold across *all* trades under
   *any* model is **0.29 days (~7 hours)**; entries are days apart. So no two
   positions were ever open at once: **scenarios 3–4 (concurrent) are byte-for-
   byte identical to scenarios 1–2 (single)** — utilization 0, the cap-of-3
   never bound, combined exposure = single-position worst. This is the honest
   "the design choice didn't matter here" outcome the brief anticipated. It also
   means **"let winners run" never actually ran long** — every exit resolved
   within hours, same fast-resolution regime as the prior study.

## Cross-checks (the study is only meaningful if these hold)

| Check | Expected | Got |
|---|---|---|
| Stopped baseline on snapshot | 8 / 4–4 / +2.86R / PF 1.43 / maxDD 3.72R | **exact** |
| `first_profit` all-8 ungated sum | +5.70R (prior `trend_no_stop.py`) | **+5.70R** |

Entries identical by construction → the three-way per-trade reconciliation is
valid.

## The 20-run matrix

Net R is per scenario; long-only cells are **n=1**; concurrent = single (no
overlap). "worst MAE" reported in % **and** R (the unit-illusion catch).

| Exit model | long (n=1) | **short (n=7)** | both (n=8) | worst MAE %/R | net w/o top-2 (short) |
|---|---|---|---|---|---|
| first_profit | +0.81 | **+4.90** | +5.70 | −1.15% / −5.57R | **−2.46** |
| fib_target | +3.01 | **+1.70** | +4.71 | −1.15% / −5.57R | −3.96 *(flips sign)* |
| resistance_rejection | +1.09 | **+4.88** | +5.97 | −1.15% / −5.57R | −7.49 *(one trade)* |
| min_move_first_profit | +0.81 | **+4.90** | +5.70 | −1.15% / −5.57R | −2.46 *(inert)* |
| trailing_once_profitable | +1.12 | **+9.53** | +10.65 | **−0.49% / −2.95R** | **+0.75** *(only survivor)* |

(Concurrent scenarios omitted — identical to single, since no two positions ever
overlapped. Full 30 cells, including `*_concurrent` with `max_concurrent=1` and
zero utilization, are in the JSON.)

**The "net without top-2" column is the discipline check the brief demanded.**
On the short side (the only side with a sample), *every* model except trailing
goes **negative** once its two best trades are removed — first-profit +4.90R →
−2.46R, fib flips sign on its single best, resistance_rejection is one +11.78R
trade sitting on −7.49R of losers. Only `trailing_once_profitable` stays positive
(+0.75R) after removing its top two — and that thin residual is the profit-
locking trailing *stop* limiting the losers, on n=7 in one chop-down window.

## Both-directions, per model (n=8 — the real content)

### first_profit — +5.70R (baseline)
The prior study's result, reproduced. 6 reversion, 2 bias_flip. Established
NULL: regime-and-asymmetry-flattered, one-trade-sensitive, n=8. Included only as
the comparison point.

### fib_target — +4.71R — **the principled fix underperforms**
Letting winners run to the engine's own fib-extension target returned *less*
than first-profit. The three-way shows why: on the two early shorts (01-08,
01-19) **the 4H bias flipped before the target was reached**, so the brake cut
them (fp +2.95/+0.76 → fib +0.57/+0.59). Holding longer for the target exposes
the trade to the brake — **4 of 8 exited via bias_flip vs first-profit's 2**.
The intended fix and the catastrophe brake are in direct tension. Dominance:
net-excluding-top-2 = **−1.58R** — the positive total is its two best trades
(03-22 +3.27, 05-24 +3.01); without them it is negative.

### resistance_rejection — +5.97R — **fails the dominance check outright**
Top single trade **+11.78R**; **net excluding it = −5.80R** →
`single_trade_flips_sign = TRUE`. The entire positive result is one rejection
trade; the other seven net negative (5 exited on the brake, only 3 on an actual
rejection). This is exactly the "headline is one lucky trade" failure that
killed the prior study's number. NULL.

### min_move_first_profit — +5.70R — **inert**
Identical to first-profit to the decimal. The 1R arm threshold is non-binding:
because the R:R gate admits tight structural stops, 1R is a tiny price move
(~0.2–1%), reached before the profitable close on every trade. The gate changed
nothing. NULL, no effect.

### trailing_once_profitable — +10.65R — **best, and the most interesting, but not proven**
Highest return *and* the shallowest tail (worst MAE −0.49% / **−2.95R** vs the
−5.57R hostage everywhere else). 7 of 8 exited via the trailing stop. But four
caveats, in order of weight:
- **One trade is 63% of it.** The 03-18 short returned **+6.76R** (trailing rode
  a sharp intraday drop far past the +2.39R the target took and the +4.41R
  first-profit took). Net-excluding-top-1 = +3.89R (still positive — it does
  *not* flip sign, unlike resistance_rejection), but the headline leans hard on
  one sharp short.
- **It didn't actually "let winners run."** Max hold 0.21 days. The gain is from
  capturing more of *fast* moves, not from patience — the same kind-to-shorts
  chop window as before.
- **It works by putting a stop back in.** "Trailing once +1R" is a profit-
  locking *stop*. The best-performing variant is the one that **reintroduces
  disciplined risk control** (which is also why its tail is the shallowest — it
  exits the two prior hostages at 03-17 +0.05 and 04-30 −0.63 instead of letting
  the brake catch them at −2.74/−4.34). This is the opposite of "no stop."
- **n = 8, 7 shorts, one window.** Same small-sample, same regime.

## Trade-by-trade three-way reconciliation (both-directions, trailing vs the two baselines)

| Entry | Dir | Stopped | first_profit | **trailing** | Held |
|---|---|---|---|---|---|
| 2026-01-08 | SHORT | stop −1.49 | rev +2.95 | trail **+2.02** | 0.17d |
| 2026-01-19 | SHORT | target +2.17 | rev +0.76 | bias_flip +0.59 | 0.21d |
| 2026-03-17 | SHORT | stop −1.46 | bias_flip −2.74 | trail **+0.05** | 0.08d |
| 2026-03-18 | SHORT | target +2.39 | rev +4.41 | trail **+6.76** | 0.12d |
| 2026-03-19 | SHORT | target +1.96 | rev +1.99 | trail +1.62 | 0.08d |
| 2026-03-22 | SHORT | stop −1.99 | rev +1.88 | trail −0.89 | 0.08d |
| 2026-04-30 | SHORT | stop −1.73 | bias_flip −4.34 | trail **−0.63** | 0.08d |
| 2026-05-24 | LONG | target +3.01 | rev +0.81 | trail +1.12 | 0.12d |

The trailing stop's edge over first-profit is: (a) the 03-18 ratchet (+6.76 vs
+4.41), and (b) rescuing the two first-profit hostages (03-17, 04-30) by exiting
them near breakeven instead of on the brake. Both are the trailing *stop* doing
the work — not "letting winners run."

## Short-only, per model (n = 7 — the actual test)

The short-only cut removes the single long and isolates the seven shorts. It
tells the same story as both-directions (as it must — 7 of 8), with the
dominance check sharper at n=7:

| Model | short net | wins | net w/o top-1 | net w/o top-2 | read |
|---|---|---|---|---|---|
| first_profit | +4.90 | 5 | +0.49 | **−2.46** | carried by 2 trades |
| fib_target | +1.70 | 5 | **−1.57** (flips) | −3.96 | brake beats the target |
| resistance_rejection | +4.88 | 3 | **−6.90** (flips) | −7.49 | one +11.78R trade *is* the result |
| min_move_first_profit | +4.90 | 5 | +0.49 | −2.46 | inert (= first_profit) |
| trailing_once_profitable | +9.53 | 5 | +2.77 | **+0.75** | only model positive w/o its top 2 |

**Short-side verdict: no exit rule establishes an edge at n = 7.** Four of five
go negative once their top one or two trades are removed; `min_move` is inert;
only `trailing_once_profitable` survives removing its top two — and by only
+0.75R, driven by its trailing *stop* limiting losers, on a single chop-down
window. This is the honest picture the brief's "test the shorts" instruction was
meant to expose: the short side, where all the signal in this window lives, does
not carry a robust edge for any let-winners-run exit.

## Verdict per scenario

- **Long-only (single & concurrent): NO VERDICT — n = 1.** Not evaluable in this
  window. The design's long-side support, which the brief specifically wanted,
  remains untested because only one long entry exists here. State plainly: this
  is a power failure, not a result. (See "Scoping a long-side sample" below.)
- **Short-only (single & concurrent, n = 7): NULL / inconclusive.** All five
  exits fail the dominance check except trailing, which barely survives (+0.75R
  without its top two) via its trailing stop — thin, one-window, stop-driven.
- **Both-directions (single & concurrent, identical): NULL / inconclusive**
  (= short-only + the one long). No exit rule produces a defensible edge:
  - the principled fix (`fib_target`) *underperforms* first-profit because the
    bias-flip brake cuts winners before the target;
  - `resistance_rejection`'s positive total is a single trade (flips sign
    without it);
  - `min_move` is inert;
  - `trailing_once_profitable` is the standout (+10.65R, best tail) but is
    one-trade-heavy (63%), never actually held long (≤0.21d), regime-bound
    (n=8, 7 shorts), and achieves its result by **reintroducing a trailing
    stop** — i.e. the lesson is "disciplined risk control helps," not "no stop
    plus let-run helps."
- **Concurrency: did not matter.** Zero overlap; scenarios 3–4 ≡ 1–2.

**No forward-test candidate is promoted.** The fix does not soften the verdict:
correcting the exit did not reveal an edge; it revealed that (a) the brake and a
run-to-target exit fight each other, and (b) the only variant that looks good is
the one that adds a stop back.

**The one idea worth a purpose-built, pre-registered next study** (not licensed
by this n=8, short-heavy run): **`trailing_once_profitable` as a stand-alone
design** — a profit-locking trailing stop with *no* fixed target and the bias-
flip brake — evaluated on a window with a real long side and at least one
sustained trend, with the trail trigger/distance pre-registered (here fixed at
1R/1R, flagged, untuned). That is a different experiment; combinations of these
five exits remain deferred pending a separate go-ahead.

## Scoping a long-side sample

**Why the shortage is structural.** The live engine is 4H-bias + **1H-trigger**
BTC. The 1H snapshot is capped at Hyperliquid's ~5,000-candle retention
(`data/feed.py`), i.e. ~208 days (2025-12 → 2026-07) — a predominantly
downtrend/chop window, so bullish 4H bias was rare and only one long cleared the
confluence + R:R gate. The bottleneck is **data span × regime**, not the exit
logic. Options to fix it, cheapest first:

- **A — Coarser trigger over the in-hand 4H snapshot (same day, ~zero data).**
  Run the same confluence entries on a higher trigger (e.g. 1D bias / 4H
  trigger). The frozen 4H snapshot already spans **~2.3 years (2024-03 →
  2026-07)**, including the 2024 bull → materially more long entries. *Caveat:*
  it tests a coarser variant, **not** the live 4H/1H engine, so results aren't
  directly comparable to the +2.86R baseline. Good as a fast directional-balance
  sanity cut before investing in B.
- **B — External deep-history 1H source (recommended true fix, ~an afternoon).**
  Add a one-off fetcher for BTC 1H klines from a long-retention venue
  (Binance/Bybit/Coinbase, REST or ccxt) back to ~2020, freeze as a new
  write-once snapshot in the existing `load_snapshot` schema, and re-run the
  **exact** live 4H/1H engine across multiple full cycles (2021 bull, 2022 bear,
  2024 bull, …). This yields a real long-side sample for the actual config.
  *Caveat:* cross-exchange BTC differs slightly (perp vs spot, funding,
  microstructure) — fine for structure-based entry/exit research, not for exact
  fill realism. Pre-register a held-out window.
- **C — Multi-asset pooling (not recommended as primary).** The 7-asset universe
  is only frozen at 1D; fetching 1H per asset hits the same 208-day Hyperliquid
  cap → the same down-window, and the assets co-move (N_eff ≈ 2, per the factor
  study), so pooling mostly multiplies *shorts*, not longs.
- **D — Forward accumulation (zero curve-risk, slow).** The dry-run forward test
  (`trend_forward_marks`) already logs live; longs accrue as the market spends
  time in bullish bias. Complementary, calendar-bound — keep it running
  regardless.

**Recommendation:** **B** for a genuine long-side test of the live engine (deep
external 1H, multi-cycle, one pre-registered holdout), with **A** as a same-day
pre-check on whether longs even behave differently. Whatever the source, apply
the program's discipline: pre-register the exit (fix on
`trailing_once_profitable`, the one dominance survivor), fix the split, one
holdout, report every cell.

## Design choices (flagged, not tuned)
Concurrent cap **3**; min-move arm **1R**; trailing arm **1R**; trailing
distance **1R** (the brief fixed the trigger, left the distance open — 1R for
symmetry). None were swept.

## Reproduce
```powershell
python scripts/trend_let_winners_run.py --selfcheck
python scripts/trend_let_winners_run.py --phase run
```
