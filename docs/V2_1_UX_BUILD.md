# V2.1 UX Build — Severity Tiers, Dashboard, Web View

## Research Findings

Source: "Prop Trading Bot Telegram UX" PDF (Aetheris-QS paper). Findings
spot-checked against the V2 build report's corrections before adoption.

**Adopted:**
- 5-tier severity framework → mapped to Telegram `disable_notification`:
  T1 diagnostics never broadcast (logs/Supabase only); T2 (regime shift,
  heartbeat, daily summary) delivered silent; T3 setup/entry normal;
  T4 risk events (exits) normal-loud; T5 halts loud. Custom alert sounds
  are a Telegram client-side setting — cannot be forced by the bot.
- WHY-with-exact-levels on every alert (already house style; extended to
  the new regime-shift alert).
- Dashboard layout density (account baseline / equity / buffers /
  positions / open risk) — honest fields only.
- Private-chat routing rationale (group 20 msg/min vs private 30/s) —
  already our architecture (control plane in DM, broadcast channel for
  alerts).

**Rejected (with reasons):**
- Chamber A/B dual-process HMAC signing, Ollama/Gemma, core pinning —
  out of scope per locked constraints.
- Direct Hyperliquid execution scaffolds (`hyperliquid.exchange`) —
  violates Propr-only execution (V2 correction C1).
- `[Buy 1 BTC]` fixed-notional buttons (the paper's own Scaffold B) —
  violates the risk-%-only rule; our trade panel already risk-budgeted.
- Fabricated performance stats (Win Rate 58.2%, Sharpe 1.85, expectancy
  blocks) — no trades have been executed; nothing is displayed that
  would require invented data (V2 correction C3).
- Alternative indicator math (Fisher 9-SMA signal line, |F|≥1.5 extreme
  gate, OBV Z-score ≥ +1.5, ATR filter) — conflicts with the verified
  Rev-2/3 research and locked facts (Fisher period 10, trigger = 1-bar
  delay; OBV vs 20-SMA). Could become future toggleable indicators via
  the existing indicator_config pattern if ever researched properly.
- 5s auto-editing Telegram dashboard — deferred; the web dashboard
  covers live-view at lower complexity.

## Changes

1. **Severity tiering** — `alerts/telegram.py` `send(silent=)`;
   tier tags in every header (`[T2]`…`[T5 HALT]`); NEW
   `format_regime_shift` fired by the engine once per bias change,
   silent, with the exact level/condition. Heartbeats + daily summaries
   now silent.
2. **Telegram /dashboard** — reads engine-published paper state from
   Supabase (new telemetry columns `open_positions`, `open_risk_usd`,
   `cb_halted`; new `market_state.bias_reason`). Shows engine + breaker
   state, mode/TF, indicator summary, bias WITH the level that set it,
   structural setups w/ live R:R, loss buffers, paper position + open
   risk. Live-position fetch unchanged (separate ticket).
3. **Web dashboard** — `web/` (own Vercel project `btc-signal-bot-dash`,
   alias https://btc-signal-bot-dash.vercel.app). FastAPI + single-page
   shell served by the same function (Bullphoric-pattern catch-all
   rewrite). View-only: read-only Supabase queries, mechanically
   enforced by tests (no trading imports, no write SQL). Auth: password
   login → HMAC-signed HttpOnly cookie, or `x-api-key` header;
   fail-closed 503 when `DASHBOARD_API_KEY`/`DASHBOARD_PASSWORD` unset
   (verified live before env vars were configured). 15s polling,
   mobile-first.

## Repo Structure (new/changed)

```
alerts/telegram.py        # silent flag -> disable_notification
alerts/formats.py         # tier tags + format_regime_shift
main.py                   # regime-shift detection; silent tiers; telemetry fields
db/schema.sql             # bias_reason, open_positions, open_risk_usd, cb_halted
db/store.py               # get_latest_telemetry; extended writers
telegram_control/handlers.py  # /dashboard rebuild
web/
├── api/index.py          # FastAPI: /, /api/login, /api/status, /api/equity, /api/events
├── api/dashboard.html    # single-page shell (vanilla JS, 15s poll)
├── vercel.json           # catch-all rewrite -> /api/index
└── requirements.txt      # fastapi, psycopg[binary]
tests/test_severity_tiers.py
tests/test_web_dashboard.py
```

## Git Commits
1. `feat: severity-tiered alerts + regime-shift broadcasts`
2. `feat: dashboard at-a-glance upgrade + cross-process paper state`
3. `feat: password-gated web dashboard (vercel, fail-closed)`
4. `docs: v2.1 ux build doc` (this file + deploy fixes)

## Open Items
1. **Vercel env vars (user action):** project `btc-signal-bot-dash` →
   Settings → Environment Variables: `DATABASE_URL` (Supabase SESSION
   pooler URI), `DASHBOARD_API_KEY` (long random secret),
   `DASHBOARD_PASSWORD` (login password) → redeploy. Until then the
   dashboard is intentionally dead (503).
2. Web v1 is view-only; action buttons (confirm-gated) possible later.
3. "Live positions unavailable" in /dashboard — separate ticket
   (pre-purchase state; resolves when a challenge account exists).
4. T4/T5 loudness beyond default notification (custom sounds) is a
   Telegram client setting on the channel — configure per device.
5. Regime-shift alert fires on bias-label change only (not volatility
   expansion — that Aetheris trigger has no defined math in our stack).
