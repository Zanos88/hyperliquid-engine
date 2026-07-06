# Research Findings

All items below are cited to a live source as of 2026-07-06. Anything that
could not be verified from public documentation is explicitly flagged as
an assumption — none of it is used as a hard fact elsewhere in this repo.

## 3.1 Propr API / SDK

**Source:** [Propr Developers](https://www.propr.xyz/developers), backed by
the public docs repo [github.com/XBorgLabs/propr-docs](https://github.com/XBorgLabs/propr-docs)
(`docs/api.md`), and the live OpenAPI spec at
[propr.xyz/openapi.json](https://propr.xyz/openapi.json).

- **Base URL (live):** `https://api.propr.xyz/v1/`
- **Auth:** `X-API-Key` HTTP header, key format `pk_live_...`, generated
  from Settings at `app.propr.xyz`. Optional `X-Builder-Code` header
  (`builder_...`) for usage attribution — not required.
- **Rate limit:** 1,200 requests/min per API key (all authenticated
  endpoints share this budget).
- **Official SDK:** Yes — but distributed as source, not packaged.
  - Python: `python/propr_sdk.py` in the docs repo (copy-in module, not a
    PyPI package). Runtime deps: `requests`, `python-ulid`, `websockets`,
    `python-dotenv`.
  - JS/TS: `javascript/propr-sdk.ts`, requires `ulid`.
- **Order placement:** `POST /accounts/{accountId}/orders` — body includes
  `intentId` (client-generated ULID for idempotency), `asset`, `quantity`,
  `side`, `type`, `positionSide`. `GET` same path lists/filters orders.
  Cancel: `POST /accounts/{accountId}/orders/{orderId}/cancel`.
- **Position query:** `GET /accounts/{accountId}/positions` — returns
  `positionId`, `quantity`, `entryPrice`, `unrealizedPnl`,
  `liquidationPrice`, `leverage`, `notionalValue`, `marginUsed`,
  `realizedPnl`.
- **Account/equity query:** **ASSUMPTION — needs manual confirmation.**
  Neither `docs/api.md` nor the OpenAPI spec expose a dedicated
  account-equity or balance endpoint. The closest available data is
  position-level (`notionalValue`, `marginUsed`, `unrealizedPnl`,
  `realizedPnl`) and challenge-attempt endpoints
  (`GET /challenge-attempts/{attemptId}`), which may carry a starting/
  current balance field not visible in the fetched docs excerpt. Before
  Stage 2 wires up any equity-dependent logic against the real account,
  confirm directly with Propr (support/Discord) which endpoint returns
  live total equity, or inspect the full `openapi.json` response schema
  for `challenge-attempts` and any `/accounts/{accountId}` (non-suffixed)
  path.
- **WebSocket:** mentioned as available (e.g. a `position.updated` event)
  but no endpoint URL or message schema was found in the fetched docs.
  **ASSUMPTION — needs manual confirmation** if Stage 2 wants
  push-based position updates instead of polling.
- Other endpoints found, not needed for Stage 1: `GET /users/me`,
  `GET /accounts/{accountId}/trades`,
  `GET/PUT /accounts/{accountId}/margin-config/...`,
  `GET /challenges`, `GET /challenge-attempts[/​{id}]`,
  `GET /leverage-limits/effective`, `GET /health[/services]`.

This repo's `execution/propr_stub.py` (Section 7) shapes its method
signatures around the confirmed order/position endpoints above and marks
the equity lookup as an open TODO pending the confirmation above.

## 3.2 Fisher Transform (1H entry trigger)

**Source:** [TradingView — Fisher Transform](https://www.tradingview.com/support/solutions/43000589141-fisher-transform/),
[ForexBee — Ehler Fisher Transform Guide](https://forexbee.co/ehler-fisher-transform/),
original method by John Ehlers ("Using the Fisher Transform", *Stocks &
Commodities*, 2002).

- **Formula:**
  1. Normalize price into `[-1, 1]` over a lookback window `N` (default
     **9** in Ehlers' original publication and TradingView's reference
     implementation; ForexBee also cites 9 as the common default, with 10
     seen in some platform ports):
     `x = 2 * ((price - min(N)) / (max(N) - min(N)) - 0.5)`, clamped to
     `[-0.999, 0.999]` and smoothed with a small EMA factor (Ehlers uses
     `x = 0.33 * 2 * (...) + 0.67 * x_prev`) to avoid the `ln` blowing up
     near the bounds.
  2. Fisher Transform: `Fisher = 0.5 * ln((1 + x) / (1 - x)) + 0.5 * Fisher_prev`.
  3. **Trigger/signal line** = Fisher value from **one bar prior**
     (`Fisher[t-1]`), i.e. the Fisher line lagged by 1 — this is the
     standard construction, not a separately-computed indicator.
- **Chosen parameter:** `N = 9` (Ehlers' original default; most
  conservative and most widely cited — TradingView's built-in script and
  ForexBee both default here, avoiding an unsourced deviation).
- **Bullish cross:** `Fisher[t-1] <= Trigger[t-1]` and `Fisher[t] > Trigger[t]`
  — i.e. Fisher line crosses **above** its own prior-bar value.
- **Bearish cross:** `Fisher[t-1] >= Trigger[t-1]` and `Fisher[t] < Trigger[t]`
  — Fisher line crosses **below** its own prior-bar value.

## 3.3 On-Balance Volume (1H confirmation)

**Source:** [Wikipedia — On-balance volume](https://en.wikipedia.org/wiki/On-balance_volume),
[StockCharts ChartSchool — OBV](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv),
[Fidelity — OBV](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/obv).
Originated by Joseph Granville, *Granville's New Key to Stock Market
Profits* (1963).

- **Formula:**
  - if `close[t] > close[t-1]`: `OBV[t] = OBV[t-1] + volume[t]`
  - if `close[t] < close[t-1]`: `OBV[t] = OBV[t-1] - volume[t]`
  - if `close[t] == close[t-1]`: `OBV[t] = OBV[t-1]`
- **Confirmation rule (chosen):** OBV above its own N-bar simple moving
  average, with the OBV also having risen over the last bar
  (`OBV[t] > OBV_SMA(N)[t]` and `OBV[t] > OBV[t-1]`) for a "rising"
  confirmation (mirror with `<` for "falling"). StockCharts' ChartSchool
  explicitly documents overlaying a moving average on OBV as the standard
  way chartists smooth it for trend confirmation — this is more robust
  than a bare single-bar OBV delta, which is noisy on an hourly chart.
  Default `N = 20` (20 hourly bars ≈ same order of magnitude as the
  Fisher lookback's timeframe context; configurable in `config.yaml`).
  **ASSUMPTION flag:** the specific N=20 window is this repo's choice, not
  a value found in a cited source — StockCharts does not prescribe a
  fixed period for the OBV moving average. Treat as a tunable default, not
  a verified constant.

## 3.4 Market data feed

**Source:** [Hyperliquid Docs — Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint),
[Hyperliquid Docs — Tick and lot size](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size).

- **Endpoint:** `POST https://api.hyperliquid.xyz/info`, header
  `Content-Type: application/json`, body:
  ```json
  {"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "1h", "startTime": <ms>, "endTime": <ms>}}
  ```
  Supported intervals include `1h` and `4h` (both needed here). Response
  is an array of `{T, t, o, h, l, c, v, n, s, i}` objects (`t`/`T` = open/
  close time ms, `o/h/l/c` = OHLC strings, `v` = volume, `n` = trade
  count). Only the most recent 5,000 candles per request are returned —
  sufficient for the swing-detection lookback windows used here.
- **Rate limit:** not explicitly published for the public `/info` REST
  endpoint in the fetched docs (a per-user weight-based limit exists for
  authenticated/exchange actions, exposed via a `userRateLimit` query, but
  that governs order actions, not public info reads). **ASSUMPTION —
  needs manual confirmation** if polling frequency needs tightening beyond
  the conservative interval this repo uses (candle-close driven, i.e. at
  most one call per open symbol per closed 1H/4H candle — far below any
  plausible throttle).
- **BTC-PERP quantity step:** Hyperliquid's perpetuals metadata
  (`szDecimals` field from the `meta` info request) reports **`szDecimals
  = 5`** for BTC, i.e. a minimum size increment of **0.00001 BTC**. This
  repo's `risk/sizing.py` truncates down to this step by default but
  treats it as configurable (`btc_sz_decimals` in `config.yaml`) since the
  value should be re-verified against the live `meta` response, not
  hardcoded permanently — Hyperliquid can change per-asset metadata.

## Needs manual confirmation from user (consolidated)

1. **Propr account/equity endpoint** — not found in public docs; needed
   before Stage 2 execution work starts (Stage 1 does not call it).
2. **Propr WebSocket schema** — mentioned but undocumented in what was
   fetched; only matters for Stage 2 push-based updates.
3. **OBV moving-average window (N=20)** — this repo's own reasonable
   default, not a value drawn from a cited source. Revisit after any
   forward-testing.
4. **Hyperliquid `/info` rate limit for public reads** — not explicitly
   published; current candle-close-driven polling cadence is
   conservative, but should be confirmed if the call frequency ever
   increases (e.g. adding more symbols).
