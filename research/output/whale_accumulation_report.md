# Whale Accumulation → Forward Return Study

**Pre-registered:** 2026-07-20  
**Script:** `scripts/whale_accumulation_study.py`  
**Source data:** `research/data/source/whale_alerts.json` and `discovered_tokens.json`  |
**Cached DexScreener:** `research/data/dexscreener_cache/`  |
**Results JSON:** `research/output/whale_accumulation_results.json`

---

## Question

Does a whale-accumulation event (`whale_alerts` where `trigger='entry'`
and `delta_pct > 0`) precede a measurable USD-price gain in the associated
token, beyond a random-entry baseline?

## Method (pre-registered)

All rules below were written *before* any return calculations were computed.

### Entry rule
- **Source:** `whale_alerts.json` (committed at `research/data/source/whale_alerts.json`)
- **Signal:** alert with `trigger='entry'`, `delta_pct > 0`, and
  `price_usd IS NOT NULL`
- **Entry price:** `price_usd` at alert time
- **Event deduplication:** multiple alerts for the same token within 5
  minutes at the same price (±1%) are grouped → one representative event
  (last-in-cluster kept). Prevents double-counting when the bot's cluster
  detection fires on several wallets simultaneously.

### Holding windows and exit rule
Three fixed forward horizons, tested independently:

| Horizon | Label |
|---------|-------|
| 1 hour  | 1h    |
| 6 hours | 6h    |
| 24 hours| 24h   |

**Exit price:** `price_usd` of the nearest alert whose timestamp is
`>= entry_time + horizon`. If no such alert exists within 48 hours, the
event is discarded (right-censored).

This uses *alert-to-alert* price observations — it is NOT continuous
OHLCV. Prices are only sampled at moments when the bot detected wallet
activity.

### Baseline
Random timestamps uniformly drawn within each token's date range
(`alerted_at` min → max), then resolved to the nearest subsequent alert
with a price. The same forward-return logic is applied. 20× baseline
events per signal event (per token), for ~4,000 baseline events per
horizon.

### Significance
- **Primary:** one-sided permutation test (10,000 shuffles) — tests
  `mean(signal return) > mean(baseline return)`
- **Secondary:** Welch's t-test (two-tailed)
- **Effect size:** Cohen's d with 95% CI for mean difference
- **Multiple testing correction:** Bonferroni for 3 horizons
  (α = 0.05 / 3 = 0.0167)
- **Minimum events:** 10 deduped events to report; 30 to call it
  "promotable"

## Results

### Whale token coverage

| Token | Address | Signal events (raw) | Deduped events (1h) | Date range |
|-------|---------|---------------------|---------------------|------------|
| ALON  | `8XtRWb4u...` | 99 | 36 | May–Jul 2026 |
| ANSEM | `9cRCn9rG...` | 100 | 54 | May–Jul 2026 |
| NEET  | `Ce2gx9KG...` | 3 | 3 | Jun 2026 |
| TROLL | `5UUH9RTD...` | 3 | 3 | Jun 2026 |
| **Total** | | **205** | **96** | |

### Forward returns vs random baseline

| Horizon | Signal mean | Baseline mean | Δ | Perm p | d | Note |
|---------|------------|---------------|---|--------|---|------|
| **1h** | +8.33% | +7.07% | +1.26% [-7.83%, +10.35%] | 0.3189 | 0.037 | Not significant. |
| **6h** | +34.67% | +12.25% | +22.42% [-2.41%, +47.25%] | **0.0058** | 0.343 | Raw p significant but pseudoreplicated — 95.5% from ANSEM. |
| **24h** | +116.63% | +46.90% | +69.73% [-5.45%, +144.91%] | **0.0045** | 0.353 | Raw p significant but pseudoreplicated — 99.8% from ANSEM. |

**Pseudoreplication correction:** All three horizons are classified as **not significant** after accounting for token-level clustering. Overlapping forward windows on the same token are treated as independent events in the permutation test, inflating the effective sample size. With only 4 tokens (effectively 1 driver), a cluster-robust p-value cannot be computed (n_clusters < 5). The raw perm-p values are reported above for transparency; they should not be interpreted as evidence of a generalizable effect.

**1h:** Not significant by any measure. Signal win rate (58%) is *below* baseline (68%),
meaning the higher signal mean comes purely from right-tail skew (a few
big winners) while most signals underperform random entry.

**6h:** Not significant after the pseudoreplication correction above (raw
perm-p = 0.0058 < α, but the effect is 95.5% ANSEM and effective n ≈ 1
token). Raw Δ ≈ +22pp, signal win rate 60% vs baseline 53%, effect size
small-to-medium (d = 0.34) — none of which survives token-level clustering.

**24h:** Not significant after the pseudoreplication correction above (raw
perm-p = 0.0045 < α, but the effect is 99.8% ANSEM and effective n ≈ 1
token). Raw Δ ≈ +70pp, signal win rate 72% vs baseline 71% (no edge in hit
rate, only magnitude), effect size small-to-medium (d = 0.35).

### Per-token breakdown (drives the result)

**24h (the strongest signal):**

| Token | Events | Mean return | Win rate |
|-------|--------|-------------|----------|
| ANSEM | 50 | **+207.29%** | **90%** |
| ALON  | 34 | +0.17% | 47% |
| NEET  | 2 | +4.09% | 50% |
| TROLL | 3 | +0.65% | 67% |

The entire 24h effect is **ANSEM**. Without ANSEM, the remaining 39 events
average +0.41% (n=39) — *below* the +46.90% random baseline (−46.49pp). At
6h the ex-ANSEM mean is +3.50% (n=42) vs a +12.25% baseline (−8.75pp). The
non-ANSEM whale-accumulation events do not merely fail to beat random entry;
they underperform it.

**6h:**

| Token | Events | Mean return | Win rate |
|-------|--------|-------------|----------|
| ANSEM | 53 | **+59.36%** | **70%** |
| ALON  | 36 | +3.30% | 42% |

Same pattern. ANSEM is the sole driver.

### Current DexScreener state

| Symbol | Current price | 24h Δ | Liquidity | FDV |
|--------|-------------|-------|-----------|-----|
| NEET   | $0.01880 | +0.6% | $1.1M | $18.8M |
| ANSEM  | $0.19190 | -0.9% | $2.0M | $191.9M |
| TROLL  | $0.04379 | -3.7% | $2.5M | $43.7M |
| ALON   | $0.00135 | +10.6% | $0.3M | $1.3M |

ANSEM's price today ($0.19) is ~42× higher than its first accumulation
entry ($0.0046), confirming it was a genuine multi-bagger. But this is
one token with one major pump — not a replicable strategy.

## Conclusion

**"Does whale accumulation predict forward returns?"**

At the 1h horizon: **No.** Signal and baseline are indistinguishable
(p = 0.32). The higher mean return is an artifact of right-tail skew.

| At 6h and 24h: **Raw permutation p is significant, but this is an artifact of
  pseudoreplication.** Overlapping forward windows on the same token are treated
  as independent events, inflating effective n. The 24h effect (Δ ≈ +70pp, d = 0.35)
  comes almost entirely from ANSEM (99.8% of total return), which ran from ~$0.005
  to ~$0.19 during the study period. Every other token shows essentially zero
  predictive power.

**Practical assessment:** The effect is not promotable as a general
signal. With only 4 tokens across 2 months of data, we cannot distinguish
between (a) whale accumulation genuinely predicts forward returns and
(b) one token happened to pump during the observation window. The latter
is the more parsimonious explanation.

## Mandatory Caveats

1. **Sample size.** `whale_alerts` and `discovered_tokens` are capped at
   1000 rows by the PostgREST server-side limit. This is a
   recent-window sample, not a representative population.

2. **Survivorship bias.** The `filter_rejections` table is EMPTY, meaning
   every token in our dataset passed the bot's filter. We never see the
   tokens the bot discarded — any apparent hit rate is upward-biased.

3. **Price measurement.** DexScreener provides current/recent pair data,
   not historical OHLCV. Forward returns were measured from
   alert-to-alert price observations (irregular sampling at wallet
   activity events), not continuous price series. The exit price is
   the nearest observed alert price at or after the horizon — not the
   exact price at that moment.

4. **Token count.** Only 4 unique tokens have whale alerts in the
   current window. Results are heavily token-idiosyncratic. ANSEM
   accounts for >95% of the measured effect.

5. **Not a trading strategy.** The study tests a conditional
   correlation, not a tradeable strategy. It does not account for
   slippage, latency, position sizing, or the impossibility of entering
   at the exact alert price in practice.

## Files

- `scripts/whale_accumulation_study.py` — Full study pipeline
- `research/data/source/whale_alerts.json` — Input whale alert data (committed)
- `research/data/source/discovered_tokens.json` — Input discovered tokens (committed)
- `research/data/dexscreener_cache/` — Cached API responses
- `research/output/whale_accumulation_results.json` — Complete results
- `research/output/whale_accumulation_report.md` — This report
