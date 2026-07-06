# RESEARCH REPORT & BUILD SPECIFICATION
## BTC-PERP Signal Bot — Propr.xyz Challenge, Stage 1 (Signal-Only)

*(Source build brief, preserved verbatim as received. See README.md and the
other docs/ files for the executed research findings, strategy rules,
and implementation that resulted from this spec.)*

**Document status:** Self-contained build brief. The session executing this
document has NO prior context. Everything needed is in this file. Where a
fact must be researched rather than assumed, this document says so
explicitly — do not fill gaps with plausible guesses.

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

Both loss limits are equity-based (they include floating P&L) and breach on
a single touch. The strategy's own risk controls (Section 6–7) are
deliberately tighter than these limits.

## 3. Required Research (complete BEFORE writing strategy code)

Produce a "Research Findings" section with cited source URLs for each item.
If a fact cannot be verified, write "ASSUMPTION — needs manual
confirmation" next to it. Never present an unverified guess as fact.

### 3.1 Propr API / SDK
Locate Propr's current developer documentation. Confirm and cite:
authentication method, order placement endpoints, position and
account/equity query endpoints, rate limits, and whether an official
Python SDK exists. Stage 1 places no orders, but the repo's (empty)
execution module interface must match the real API's shape — so the
research must be done now, not deferred. If any part of the API
documentation is unavailable or ambiguous, STOP on that item and list it
under "Needs manual confirmation from user."

### 3.2 Fisher Transform (1H entry trigger)
Confirm the standard Fisher Transform formula (Ehlers) and the commonly
used default lookback period, with citations. Define precisely what
"bullish cross" and "bearish cross" mean (Fisher line vs. trigger/signal
line). Do not invent parameter values.

### 3.3 On-Balance Volume (1H confirmation)
Confirm the standard OBV formula with citation. Define the confirmation
rule precisely (research common practice, cite, choose one, justify).

### 3.4 Market data feed
Default decision: Hyperliquid's public market-data API for BTC-PERP OHLCV
(1H and 4H candles), since it is the execution venue.

## 4. Strategy Specification

Multi-timeframe confluence system. A trade signal exists only when the 1H
trigger agrees with the 4H structural bias. No counter-trend signals.

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
  positions and posts an exit alert when stop or target is touched by live
  price.

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
│   └── propr_stub.py        # interface only — raises NotImplementedError
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

- [ ] Research Findings section complete, every claim cited or flagged
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
