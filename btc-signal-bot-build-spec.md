# RESEARCH REPORT & BUILD SPECIFICATION
## BTC-PERP Signal Bot — Propr.xyz Challenge, Stage 1 (Signal-Only)

*(Source build brief, preserved verbatim as received — Revision 2. See
README.md and the other docs/ files for the scaffold that resulted from
this spec.)*

**Document status:** Self-contained build brief. The session executing
this document has NO prior context. Everything needed is in this file.
Where a fact must be researched rather than assumed, this document says
so explicitly — do not fill gaps with plausible guesses.

**Revision 2 — Section 3 research completed and cited (6 July 2026).**

## 1. Mission & Role

You are acting as an expert quantitative trading researcher and production
Python developer. You are building Stage 1 of a three-stage system:

- **STAGE 1 (this build):** Signal-only bot. Full strategy logic computes
  live BTC-PERP signals and posts alerts to a dedicated Telegram channel.
  No order execution of any kind.
- **STAGE 2 (future, not this build):** Same codebase deployed to an ASUS
  NUC with a Propr API execution layer added. Your Stage 1 architecture
  must allow execution to slot in as a new module without rewriting
  strategy code.
- **STAGE 3 (future):** Ongoing improvement loop.

Build Stage 1 completely. Design for Stage 2. Do not build Stage 2.

## 2. Challenge Context (static facts — treat as ground truth)

The strategy will eventually trade a Propr.xyz prop-firm challenge account
with these parameters:

| Parameter | Value |
|---|---|
| Account size | $100,000 USDC |
| Challenge type | 1-Step Classic |
| Max drawdown | 6% static → hard equity floor at $94,000 (never trails) |
| Daily loss limit | 3% → $3,000 per day (daily floor = day-start equity − $3,000, reset 00:00 UTC) |
| Profit target | 10% → $110,000 |
| Time limit | None |
| Profit split (funded) | 80% |
| Execution venue | Hyperliquid perps (via Propr's API) |
| Prohibited | HFT, martingale, grid strategies |

Both loss limits are equity-based (they include floating P&L) and breach
on a single touch. The strategy's own risk controls (Section 6–7) are
deliberately tighter than these limits.

## 3. Research Findings (COMPLETED — verify links resolve, then build)

Research conducted 6 July 2026. The build session must spot-check that
the cited sources still say what is claimed before relying on them; any
drift goes in "Open Items." Items marked ASSUMPTION still need
confirmation.

### 3.1 Propr API / SDK — VERIFIED (primary source)

**Source:** official docs repository `github.com/XBorgLabs/propr-docs`
(files: `docs/api.md`, `docs/quickstart.md`, `docs/websocket.md`,
`python/propr_sdk.py`). Clone it and read these files directly at build
time — they are the primary source.

| Item | Finding |
|---|---|
| Base URL (REST) | `https://api.propr.xyz/v1` (beta: `api.beta.propr.xyz/v1`) |
| Base URL (WS) | `wss://api.propr.xyz/ws` (connect with `X-API-Key` header; server pings every 20s) |
| Authentication | API key generated in app (format `pk_live_...`), sent as `X-API-Key` header on all authenticated requests |
| Rate limit | 1,200 requests/min |
| Account discovery | `GET /challenge-attempts?status=active` → `accountId`; all trading endpoints are under `/accounts/{accountId}/...` |
| Orders | `POST /accounts/{accountId}/orders` (batch array; 201 on create). Order types include `market`, `limit`, `stop_market`, `take_profit_market`; `timeInForce` includes `IOC`/`GTC`; closing uses `reduceOnly`/`closePosition` |
| Positions | `GET /accounts/{accountId}/positions` |
| Account / equity | `GET /accounts/{accountId}` → `balance`, `availableBalance`, `totalUnrealizedPnl`, `marginBalance`, margin fields, `highWaterMark`. **Equity = balance + totalUnrealizedPnl + isolatedPositionMargin** (per SDK docstring) |
| WS events | `account.updated`, `order.filled`, `position.updated` (and others; see `docs/websocket.md`) |
| Python SDK | Yes — `python/propr_sdk.py` in the repo; designed to be copied into the project, not pip-installed |
| OpenAPI spec | Referenced at the end of `docs/api.md` |

**Consequence for Stage 1:** shape `execution/propr_stub.py` method
signatures to match the SDK's (`setup()`, `get_account()`,
`create_order(...)`, `get_open_positions()`, `close_position()`), so
Stage 2 swaps the stub for the real SDK with no interface change.

### 3.2 Fisher Transform — VERIFIED

**Primary source:** J.F. Ehlers, *Using the Fisher Transform*, Technical
Analysis of Stocks & Commodities Vol. 20 —
https://www.mesasoftware.com/papers/UsingTheFisherTransform.pdf

- Core transform: `Fisher(x) = 0.5 * ln((1 + x) / (1 - x))`, applied to
  price normalized into −1…+1 over a rolling min/max channel.
- Ehlers' own construction normalizes over a **10-bar channel** with EMA
  smoothing (alpha ≈ 0.33) before the transform.
- Common platform defaults are period 9 or 10 (e.g. period 9:
  https://forexbee.co/ehler-fisher-transform/ ; period 10:
  https://library.tradingtechnologies.com/trade/chrt-ti-ehler-fisher-transformation.html ).
- **Trigger line** = the Fisher line delayed one bar (`Fisher[t-1]`); this
  smoothing/trigger construction is described at
  https://coinpedia.org/traders/what-is-ehler-fisher-transform/ .
- **Bullish cross:** Fisher crosses above trigger (strongest per
  literature when occurring after a trough / from negative territory);
  bearish cross is the mirror.

**Decision: period = 10** (matches Ehlers' primary paper — primary source
beats platform convention; this **supersedes Revision 1's period = 9**).

**Implementation note (standard, uncited):** clamp normalized x to
±0.999 before `ln()` to avoid singularity at ±1 — flag in code comments.

### 3.3 On-Balance Volume — VERIFIED

**Sources:** Wikipedia (formula): https://en.wikipedia.org/wiki/On-balance_volume ;
StockCharts ChartSchool (interpretation):
https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv

- Formula (Granville, 1963): running total. If close > prior close:
  OBV += volume. If close < prior close: OBV −= volume. If equal:
  unchanged.
- The absolute OBV value is meaningless (depends on series start); only
  the line's direction/trend matters — both sources agree.
- Literature does not fix one canonical confirmation rule; common
  practice is OBV trend/slope assessment, often with an MA overlay.

**Decision: confirmation = OBV above its 20-period SMA AND OBV rising
vs. the prior bar** (falling/below for shorts).

**ASSUMPTION — needs manual confirmation:** the 20-period SMA length is
a common convention, not a cited standard. Make it configurable
(`obv_sma_period`) and confirm with the user.

### 3.4 Market data feed — VERIFIED (Hyperliquid public API)

**Sources:** Hyperliquid official docs
(https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint ,
.../rate-limits-and-user-limits); endpoint reference with schema:
https://docs.chainstack.com/reference/hyperliquid-info-candle-snapshot

- **Endpoint:** `POST https://api.hyperliquid.xyz/info` with body
  `{"type":"candleSnapshot","req":{"coin":"BTC","interval":"1h","startTime":<ms>,"endTime":<ms>}}`.
  No auth, no key.
- Intervals include `1h` and `4h`. Response: array of
  `{t, T, o, h, l, c, v, n, s, i}` (open time, close time, OHLC as
  strings, volume, trade count). **Only the most recent 5,000 candles per
  interval are available** — ample for 10-bar Fisher and 4H swing
  structure.
- Rate limits are IP-weighted; `candleSnapshot` carries extra weight per
  60 candles returned — request only the lookback needed (e.g. 300
  bars), not the max.
- **Live updates:** WS `wss://api.hyperliquid.xyz/ws` offers candle
  subscriptions; acceptable Stage 1 alternative is REST polling ~30s
  after each candle close (simpler, well within limits).
- **BTC-PERP quantity step:** per-asset `szDecimals` comes from the
  `{"type":"meta"}` info request. **Do not hardcode** — query meta at
  startup and derive the step. (ASSUMPTION removed by making it a
  runtime lookup.)

### 3.5 Consolidated open items (carry into build output)

1. `obv_sma_period = 20` — convention, confirm with user.
2. Fisher period 10 chosen over 9 — primary-source rationale given;
   confirm user is happy.
3. Alert message formats (Section 8) — confirm before locking.
4. Propr-side check: confirm the $100K 1-Step Classic tier's exact
   drawdown/daily-loss percentages against `GET /challenges` (no auth)
   when the account is purchased — Section 2 figures are the user's
   stated parameters.

## 4. Strategy Specification

Multi-timeframe confluence system. A trade signal exists only when the
1H trigger agrees with the 4H structural bias. No counter-trend signals.

### 4.1 4H structural bias (context layer)
Fibonacci retracement/extension levels from the most recent completed
major swing, plus key horizontal support/resistance from prior swing
highs/lows. Output a bias state: BULLISH / BEARISH / NEUTRAL, as explicit
deterministic conditions. NEUTRAL = no trading.

### 4.2 1H entry trigger (timing layer)
Evaluated only on candle close:
- **Long trigger:** Fisher Transform bullish cross AND OBV confirmation
  rising, while 4H bias = BULLISH.
- **Short trigger:** Fisher Transform bearish cross AND OBV confirmation
  falling, while 4H bias = BEARISH.
- Any 1H trigger occurring against or without 4H bias is logged but
  generates NO alert-as-signal.

### 4.3 Exits
Every signal must carry, at generation time:
- **Stop-loss:** structural (beyond the relevant 4H S/R or swing point),
  never a bare percentage.
- **Take-profit:** next opposing 4H structural level or Fibonacci
  extension; minimum reward:risk of 2:1 — signals failing 2:1 are
  suppressed and logged.
- **Exit alerts (Stage 1):** the bot tracks its own open hypothetical
  positions and posts an exit alert when stop or target is touched by
  live price.

### 4.4 Pseudocode first
Write the full entry/exit decision tree as commented pseudocode and get it
internally consistent BEFORE writing Python.

## 5. Position Sizing (specification)

```
size(equity, entry_price, stop_price, risk_pct) -> quantity
```
- Risk per trade: 0.5–1.0% of current equity ($500–$1,000 at start).
  Default 0.75%; configurable.
- `quantity = (equity × risk_pct) / |entry − stop|`
- Quantity must be truncated DOWN to the venue's quantity step for
  BTC-PERP (research the step size; cite).
- Stage 1 computes and displays the size in alerts; nothing is executed.

## 6. Circuit Breaker (specification)

- Track running daily P&L of the hypothetical position ledger against
  day-start equity, resetting at 00:00 UTC.
- If daily P&L reaches −2.5% (−$2,500): halt all new signal generation,
  post a clearly-labeled HALT alert to Telegram, log the event, and resume
  automatically at the next UTC day rollover.
- The −2.5% halt is a deliberate buffer inside the challenge's real 3%
  daily limit. Never remove or widen it.

## 7. Repository Structure (required separation)

```
btc-signal-bot/
├── config.yaml            # account params, risk %, telegram, feature flags
├── strategy/
│   ├── bias_4h.py          # Fib + S/R structural bias
│   ├── trigger_1h.py       # Fisher Transform + OBV
│   └── signals.py          # confluence logic, signal objects, R:R gate
├── data/
│   └── feed.py             # OHLCV fetch (Hyperliquid public API)
├── risk/
│   ├── sizing.py            # position sizing function
│   └── circuit_breaker.py   # daily P&L tracking + halt
├── alerts/
│   ├── telegram.py          # NEW bot instance client
│   └── formats.py           # alert message templates
├── execution/
│   └── propr_stub.py        # interface only — raises NotImplementedError,
│                             # signatures shaped by Section 3.1 research
├── ledger/
│   └── tracker.py           # hypothetical open positions, exits, daily P&L
└── main.py                  # scheduler loop (1H/4H candle-close driven)
```

The `strategy/`, `risk/`, and `ledger/` modules must have zero imports from
`alerts/` or `execution/` — signals are data objects; delivery and (future)
execution are consumers. This is what makes Stage 2 a bolt-on.

## 8. Telegram Integration (Stage 1 alert scope)

**Hard constraint:** this is a NEW bot instance with a NEW bot token
(placeholder `TELEGRAM_BOT_TOKEN` env var) posting to a NEW dedicated
channel (`TELEGRAM_CHAT_ID` env var). There is an existing, unrelated
production bot ("Bullphoric" — ALON/TROLL/ANSEM) on the same
machine/account. Do not touch, import from, modify, or share config, code,
or Supabase tables with that bot in any way. If any naming collision or
shared-resource risk appears, rename on this bot's side.

Four alert types (all UTC-timestamped): Entry signal, Exit alert, Daily
summary (posted at 00:00 UTC rollover), Heartbeat (every 4 hours — silence
is failure).

## 9. Git Workflow

Incremental commits with clear messages, in this order:
1. `research: propr api + indicator formulas (cited) — findings doc`
2. `feat: strategy core (4h bias, 1h trigger, confluence)`
3. `feat: sizing + circuit breaker + ledger`
4. `feat: telegram alerts (new bot instance)`
5. `docs: runbook + stage-2 integration notes`

## 10. Required Output Format (of the build session)

Markdown document with H2 sections: Research Findings, Strategy Rules
(prose + pseudocode), Sizing Formula, Circuit-Breaker Logic, Repo
Structure, Telegram Integration Code, Git Commit Log, Open Items / Needs
Manual Confirmation.

## 11. Critical Reminders

- Do NOT fabricate Propr API endpoints, Fisher/OBV formulas, or any
  performance claims. Cite real sources or flag as assumption.
- Do NOT touch the existing Bullphoric bot: no shared code, config,
  tokens, channels, or Supabase tables.
- This strategy is live and unvalidated — no backtest exists. State risks
  explicitly. Never imply backtested confidence.
- Signal-only: Stage 1 must contain no code path that can place an order.
  The execution module is an interface stub that raises
  `NotImplementedError`.
- All strategy decisions evaluate on closed candles only — no intra-candle
  signal generation (prevents repainting).
- If Propr API details are genuinely unavailable or unclear, say so and
  list exactly what needs manual confirmation from the user. Do not guess.

## 12. Acceptance Criteria (Stage 1 is done when)

- [ ] Section 3 citations spot-checked at build time; drift documented
- [ ] Bot runs continuously, evaluates on 1H/4H candle closes
- [ ] Signals fire only on 4H+1H confluence with R:R ≥ 2:1
- [ ] Sizing, circuit breaker, and ledger verified with unit tests against
      synthetic data (include the tests)
- [ ] All four Telegram alert types deliver to the new channel
- [ ] Heartbeat proves liveness every 4 hours
- [ ] Zero code paths capable of order execution
- [ ] Zero contact with the Bullphoric bot's resources
- [ ] Runbook: how to start, stop, configure, and read logs

## Execution note (added by the executing session)

Per explicit user instruction, `alerts/formats.py` in this repo is a
standalone implementation — it does not import from, and was not copied
line-for-line out of, Bullphoric's alert formatting code. It may follow a
broadly similar structural pattern (emoji header, labeled fields) purely
because that is a reasonable general format for a Telegram trading alert,
not because of code sharing.

This repo was intentionally reduced to a **scaffold** (structure,
signatures, docstrings, TODOs, and a failing test suite as the
acceptance contract) for a separate build session (Fable) to implement
against. See README.md.
