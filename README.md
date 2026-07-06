# btc-signal-bot — Stage 1 (Signal-Only)

BTC-PERP multi-timeframe confluence signal bot for a future Propr.xyz
1-Step Classic challenge account. **This is Stage 1: it posts Telegram
alerts only. It cannot place an order — there is no code path capable of
it (`execution/propr_stub.py` raises `NotImplementedError` unconditionally).**

Built from [`btc-signal-bot-build-spec.md`](btc-signal-bot-build-spec.md).
See [`docs/RESEARCH_FINDINGS.md`](docs/RESEARCH_FINDINGS.md) for every
cited source behind the API/indicator choices below, and
[`docs/STRATEGY_PSEUDOCODE.md`](docs/STRATEGY_PSEUDOCODE.md) for the full
decision tree.

**This strategy is live and unvalidated — no backtest exists.** Parameters
were chosen conservatively (cited defaults where they exist) but there is
no historical performance evidence behind them. Treat every alert as an
untested hypothesis, not a proven edge.

This repo is **completely separate** from the existing Bullphoric
(ALON/TROLL/ANSEM) Telegram bot: separate Git repo, separate Telegram bot
token/channel (`BTC_SIGNAL_BOT_TELEGRAM_*` env vars), no shared code,
config, or Supabase tables.

## Strategy summary

- **4H bias** (`strategy/bias_4h.py`): fractal swing detection →
  Fibonacci retracement/extension + horizontal S/R → BULLISH / BEARISH /
  NEUTRAL.
- **1H trigger** (`strategy/trigger_1h.py`): Fisher Transform (period 9)
  cross + OBV-vs-its-own-20-SMA confirmation, evaluated only on closed 1H
  candles.
- **Confluence gate** (`strategy/signals.py`): a signal only exists when
  the 1H trigger direction matches the 4H bias. Stop is structural
  (beyond the relevant S/R/swing), target is the next opposing structural
  level, and any signal with R:R < 2:1 is suppressed and logged, not
  alerted.
- **Sizing** (`risk/sizing.py`): 0.75% equity risk per trade by default,
  truncated down to Hyperliquid's BTC quantity step.
- **Circuit breaker** (`risk/circuit_breaker.py`): halts new signals at
  −2.5% daily P&L (a deliberate buffer inside Propr's real 3% daily
  limit), resumes automatically at 00:00 UTC.
- **Ledger** (`ledger/tracker.py`): tracks the bot's own hypothetical
  open/closed positions so the Telegram channel is a complete auditable
  record, and so the circuit breaker has a real equity curve to gate on.

## Repository layout

```
config.yaml            # account params, risk %, telegram, feature flags
strategy/               # bias_4h.py, trigger_1h.py, signals.py — zero imports from alerts/ or execution/
data/feed.py            # Hyperliquid public OHLCV fetch
risk/                   # sizing.py, circuit_breaker.py
alerts/                 # telegram.py, formats.py
execution/propr_stub.py # interface stub, raises NotImplementedError everywhere
ledger/tracker.py       # hypothetical positions + daily P&L
main.py                 # scheduler loop (candle-close driven)
tests/                  # pytest unit tests against synthetic data
```

`strategy/`, `risk/`, and `ledger/` have zero imports from `alerts/` or
`execution/` — signals are plain data objects. This is what lets Stage 2
bolt an execution layer on without touching strategy code.

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in BTC_SIGNAL_BOT_TELEGRAM_TOKEN / _CHAT_ID
export $(cat .env | xargs)   # or use your process manager's env loading
python main.py
```

The bot polls every 60 seconds but only evaluates strategy logic when a
new 1H (or 4H) candle has closed — see `_last_closed_candle_time` in
`main.py`. Logs go to stdout (`logging.basicConfig`); redirect to a file
or your platform's log capture as needed.

### Stopping

`Ctrl+C` (SIGINT) or send SIGTERM to the process — there is no persisted
state beyond the in-memory `Ledger`/`CircuitBreaker` objects for Stage 1,
so a restart begins a fresh day/equity curve from `config.yaml`'s
`starting_equity_usd`. This is a known Stage 1 limitation (see Open Items).

### Configuring

Edit `config.yaml` for risk %, indicator periods, R:R minimum, and
heartbeat interval. **Never lower `risk.circuit_breaker_halt_pct` below
−2.5%** (build spec section 6/11 — it's a hard-coded constant in
`risk/circuit_breaker.py`, not read from config, specifically so it can't
be casually widened).

### Reading logs / alerts

- Console/stdout: `INFO` level per-loop status, `WARNING` on feed or
  Telegram-send failures (never a silent `except: pass`).
- Telegram channel: four alert types — entry signal, exit (stop/target),
  daily summary (00:00 UTC), heartbeat (every 4h — silence means the
  process is dead).

## Tests

```bash
python -m pytest -q
```

18 tests covering `risk/sizing.py`, `risk/circuit_breaker.py`, and
`ledger/tracker.py` against synthetic data (no live API calls).

## Stage 2 integration notes (not built here)

Stage 2 adds a Propr execution layer on an ASUS NUC. To slot it in without
touching strategy code:

1. Replace `execution/propr_stub.py`'s methods with real Propr API calls
   (`docs/RESEARCH_FINDINGS.md` 3.1 has the confirmed endpoint shapes for
   order placement/cancellation and position queries).
2. **Resolve the account-equity endpoint gap first** — no confirmed Propr
   endpoint returns live total equity (see Open Items below). `main.py`
   currently derives "equity" purely from the hypothetical ledger; Stage 2
   must decide whether to trust Propr's real equity or keep paper-tracking
   in parallel for reconciliation.
3. Wire `main.py`'s entry-signal branch to call the (now real)
   `execution/propr_stub.py` instead of only `ledger.open_hypothetical_position`
   — gated behind `feature_flags.execution_enabled` in `config.yaml`, which
   Stage 1 keeps hard-off.
4. Feed live Propr position/fill data into `ledger/tracker.py` in place of
   the price-touch simulation, so exits reflect real fills, not idealized
   stop/target execution.
5. Add reconciliation logging comparing Propr's reported equity against
   the ledger's tracked equity — any divergence should be a WARNING per
   this project's no-silent-fallback rule.

## Open Items / Needs Manual Confirmation

Full detail in `docs/RESEARCH_FINDINGS.md`. Consolidated:

1. **Propr account/equity endpoint** — not found in public docs. Blocks
   Stage 2's equity-based sizing/circuit-breaker wiring against the real
   account; does not block Stage 1.
2. **Propr WebSocket schema** — mentioned but undocumented. Only matters
   for Stage 2 push-based position updates.
3. **OBV moving-average window (currently 20)** — this repo's own
   reasonable default, not sourced from a citation. Revisit after any
   forward-testing period.
4. **Hyperliquid `/info` public rate limit** — not explicitly published.
   Current candle-close-driven polling cadence is conservative but
   unverified against a hard number.
5. **No persisted state across restarts** — Stage 1's `Ledger` and
   `CircuitBreaker` are in-memory only. A process restart mid-day resets
   the daily P&L baseline. Acceptable for a Stage 1 pilot; Stage 2 (or an
   earlier Stage 1 hardening pass) should persist ledger state (e.g. to a
   local SQLite file) if extended unattended uptime is required.

## Risk & scope reminders

- Signal-only. No backtest exists. No performance claims are made or
  implied anywhere in this repo.
- Prohibited by the Propr challenge terms and not present here: HFT,
  martingale, or grid logic.
- All strategy decisions evaluate on closed candles only (no
  intra-candle/repainting signals).
