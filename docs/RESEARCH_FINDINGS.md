# Research Findings (Revision 2 — completed 6 July 2026)

This supersedes the Revision 1 findings doc. Research conducted 6 July
2026; **the build session must spot-check that every cited source still
says what is claimed here before relying on it** — any drift goes in the
Open Items list below, not silently patched over.

## 3.1 Propr API / SDK — VERIFIED (primary source)

**Source:** official docs repository `github.com/XBorgLabs/propr-docs`
(files: `docs/api.md`, `docs/quickstart.md`, `docs/websocket.md`,
`python/propr_sdk.py`). **Clone it and read these files directly at build
time** — they are the primary source; this table is a summary, not a
substitute for reading them.

| Item | Finding |
|---|---|
| Base URL (REST) | `https://api.propr.xyz/v1` (beta: `api.beta.propr.xyz/v1`) |
| Base URL (WS) | `wss://api.propr.xyz/ws` (connect with `X-API-Key` header; server pings every 20s) |
| Authentication | API key generated in app (format `pk_live_...`), sent as `X-API-Key` header on all authenticated requests |
| Rate limit | 1,200 requests/min |
| Account discovery | `GET /challenge-attempts?status=active` → `accountId`; all trading endpoints are under `/accounts/{accountId}/...` |
| Orders | `POST /accounts/{accountId}/orders` (batch array; 201 on create). Order types: `market`, `limit`, `stop_market`, `take_profit_market`; `timeInForce`: `IOC`/`GTC`; closing uses `reduceOnly`/`closePosition` |
| Positions | `GET /accounts/{accountId}/positions` |
| **Account / equity** | `GET /accounts/{accountId}` → `balance`, `availableBalance`, `totalUnrealizedPnl`, `marginBalance`, margin fields, `highWaterMark`. **Equity = balance + totalUnrealizedPnl + isolatedPositionMargin** (per SDK docstring). This resolves Revision 1's "no equity endpoint found" gap. |
| WS events | `account.updated`, `order.filled`, `position.updated` (and others; see `docs/websocket.md`) |
| Python SDK | Yes — `python/propr_sdk.py` in the repo; **designed to be copied into the project, not pip-installed** |
| OpenAPI spec | Referenced at the end of `docs/api.md` |

**Consequence for Stage 1 scaffold:** `execution/propr_stub.py` method
names/signatures should match the SDK's — `setup()`, `get_account()`,
`create_order(...)`, `get_open_positions()`, `close_position()` — so
Stage 2 can swap the stub for the real SDK with no interface change.
(The scaffold in this repo currently uses `place_order` /
`cancel_order` / `get_positions` / `get_equity` naming from Revision 1;
**rename to match the SDK's naming above during implementation.**)

## 3.2 Fisher Transform — VERIFIED

**Primary source:** J.F. Ehlers, *Using the Fisher Transform*, Technical
Analysis of Stocks & Commodities Vol. 20 —
https://www.mesasoftware.com/papers/UsingTheFisherTransform.pdf

- Core transform: `Fisher(x) = 0.5 * ln((1 + x) / (1 - x))`, applied to
  price normalized into −1…+1 over a rolling min/max channel.
- Ehlers' own construction normalizes over a **10-bar channel** with EMA
  smoothing (alpha ≈ 0.33) before the transform.
- Common platform defaults are period 9 or 10 (period 9:
  https://forexbee.co/ehler-fisher-transform/ ; period 10:
  https://library.tradingtechnologies.com/trade/chrt-ti-ehler-fisher-transformation.html).
- **Trigger line** = the Fisher line delayed one bar (`Fisher[t-1]`);
  described at https://coinpedia.org/traders/what-is-ehler-fisher-transform/.
- **Bullish cross:** Fisher crosses above trigger (strongest per
  literature when occurring after a trough / from negative territory);
  bearish cross is the mirror.

**Decision: period = 10** — matches Ehlers' primary paper; primary source
takes precedence over platform convention. **This supersedes Revision 1's
period = 9**, which had defaulted to the more commonly-seen platform
value rather than the original paper.

**Implementation note (standard, uncited):** clamp normalized x to
±0.999 before `ln()` to avoid a singularity at ±1 — flag this in code
comments as a numerical-stability guard, not a strategy parameter.

## 3.3 On-Balance Volume — VERIFIED

**Sources:** Wikipedia (formula):
https://en.wikipedia.org/wiki/On-balance_volume ; StockCharts ChartSchool
(interpretation):
https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv

- Formula (Granville, 1963): running total. `close > prior close` →
  `OBV += volume`; `close < prior close` → `OBV -= volume`; equal →
  unchanged.
- The absolute OBV value is meaningless (depends on series start) — only
  the line's direction/trend matters; both sources agree on this.
- Literature does not fix one canonical confirmation rule; common
  practice is OBV trend/slope assessment, often with an MA overlay.

**Decision: confirmation = OBV above its 20-period SMA AND OBV rising vs.
the prior bar** (mirrored — below/falling — for shorts).

**ASSUMPTION — needs manual confirmation:** the 20-period SMA length is a
common convention, not a value drawn from either cited source. Kept
configurable (`obv_sma_period`); confirm with the user before treating it
as final.

## 3.4 Market data feed — VERIFIED (Hyperliquid public API)

**Sources:** Hyperliquid official docs
(https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint,
.../rate-limits-and-user-limits); endpoint reference with schema:
https://docs.chainstack.com/reference/hyperliquid-info-candle-snapshot

- **Endpoint:** `POST https://api.hyperliquid.xyz/info`, body
  `{"type":"candleSnapshot","req":{"coin":"BTC","interval":"1h","startTime":<ms>,"endTime":<ms>}}`.
  No auth, no key required.
- Intervals include `1h` and `4h`. Response: array of
  `{t, T, o, h, l, c, v, n, s, i}` (open time, close time, OHLC as
  strings, volume, trade count). **Only the most recent 5,000 candles per
  interval are available** — ample for a 10-bar Fisher lookback and 4H
  swing structure.
- Rate limits are **IP-weighted**; `candleSnapshot` carries extra weight
  per 60 candles returned — request only the lookback actually needed
  (e.g. 300 bars), not the max available.
- **Live updates:** WS `wss://api.hyperliquid.xyz/ws` offers candle
  subscriptions. An acceptable Stage 1 alternative is REST polling ~30
  seconds after each expected candle close (simpler, well within rate
  limits) — this is what the scaffold's `main.py` assumes.
- **BTC-PERP quantity step:** per-asset `szDecimals` comes from the
  `{"type":"meta"}` info request. **Do not hardcode** — query `meta` at
  startup and derive the step live. This removes Revision 1's
  hardcoded-default caveat entirely; `DEFAULT_BTC_SZ_DECIMALS = 5` in
  `risk/sizing.py` should only ever be a fallback value used if the live
  lookup fails (and that failure must be logged as a WARNING, never
  silent).

## Consolidated Open Items / Needs Manual Confirmation

1. **`obv_sma_period = 20`** — a common convention, not a value drawn
   from a cited source. Confirm with the user before locking it in.
2. **Fisher period 10 (not 9)** — chosen on primary-source grounds
   (Ehlers' original paper) over the more common platform default of 9.
   Confirm the user is happy with this choice; it changes signal timing
   versus a period-9 implementation.
3. **Alert message formats** (build spec section 8) — confirm exact
   wording/layout with the user before locking `alerts/formats.py`.
4. **Propr challenge tier parameters** — confirm the $100K 1-Step
   Classic tier's exact drawdown/daily-loss percentages against
   `GET /challenges` (no auth required) once the account is purchased.
   Section 2 of the build spec states the user's own stated parameters,
   not a value independently verified against Propr's API.
5. **Propr execution method naming** — this scaffold's
   `execution/propr_stub.py` currently uses placeholder method names from
   Revision 1 (`place_order`, `cancel_order`, `get_positions`,
   `get_equity`). Rename to match the verified SDK's `create_order`,
   `get_open_positions`, `close_position`, `get_account`, `setup` during
   implementation so Stage 2 is a true drop-in.
6. **Propr WebSocket message schemas** — endpoint and event names
   (`account.updated`, `order.filled`, `position.updated`) are confirmed,
   but exact payload schemas are only in `docs/websocket.md` in the
   `propr-docs` repo — read that file directly at implementation time
   rather than relying on this summary.

## Superseded from Revision 1

- Fisher period: was 9 (platform-convention default), now **10**
  (primary-source default) — see 3.2.
- Propr account/equity endpoint: was flagged as **not found**, now
  **confirmed** (`GET /accounts/{accountId}`, equity formula above) — see
  3.1.
- BTC szDecimals: was cited as a fixed default (5) with a runtime-lookup
  recommendation; now confirmed as **must be a runtime lookup**, not
  optional — see 3.4.
