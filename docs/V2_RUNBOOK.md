# V2 Runbook — Execution Engine + Control Plane (Stage 2)

**Current posture: DRY-RUN. No order has ever been dispatched, and both
arming switches are closed.** Verified at build end against Propr's
order history (read-only check — empty).

## Processes (one entrypoint each, deployment-agnostic)

| Process | Entrypoint | Role |
|---|---|---|
| Engine | `python main.py` | Candle-close strategy loop → gate → (dry-run) execution; paper ledger; telemetry; alerts |
| Guardian | `python guardian.py` | Independent WS equity watch; soft-halt floor+$500; hard-flatten floor+$200 |
| Control plane | `python -m telegram_control` | /run /pause /kill /dashboard /risk + Frame A/B buttons; auth-allowlisted |

All three share state ONLY through Postgres (`engine_state`,
`risk_params`, `pending_signals`, telemetry/ledger/risk-event tables).

## Environment variables

| Var | Used by | Notes |
|---|---|---|
| `BTC_SIGNAL_BOT_TELEGRAM_TOKEN` / `_CHAT_ID` | engine, guardian, control | Never Bullphoric's |
| `PROPR_API_KEY` | all | Secret; Railway service variable |
| `PROPR_BUILDER_CODE` | all | Sent as `X-Builder-Code` on every request |
| `DATABASE_URL` / `DATABASE_PUBLIC_URL` | all | **Supabase project `btc-signal-bot` (`lnycymeylmhjqpwtdint`, us-east-1)** since the 2026-07-07 schema-only migration. Currently the direct-connection URI (IPv6 — works from the local machine). ⚠️ Before deploying V2 processes ON Railway, switch both to the **Session pooler** URI (`aws-*.pooler.supabase.com:5432`) — Railway compute has no outbound IPv6. RLS is enabled with no policies (bot's postgres role bypasses; REST/anon surface blocked). Rollback: point both vars back at the Railway Postgres references — kept intact, dry-run-era data only. Note Railway credit was near exhaustion at migration time; the rollback window depends on it. |
| `BTC_SIGNAL_BOT_ADMIN_IDS` | control plane | Comma-separated Telegram user IDs. **Empty = everyone locked out (fail closed)** |
| `DRY_RUN` | engine, guardian, control | **Unset/anything ≠ "false" means dry-run.** Switch 1 of 2 |

## The two-switch arming rule (do not defeat)

Live order dispatch requires BOTH, independently:
1. `DRY_RUN=false` in the process environment, AND
2. `feature_flags.execution_enabled: true` in `config.yaml`.

Either alone keeps every write in dry-run (intents recorded, nothing
sent). **Go-live is out of V2 scope** — see the checklist below.

## Start / stop

Local (secrets injected from Railway, never on disk):
```bash
railway run --service btc-signal-bot python main.py
railway run --service btc-signal-bot python guardian.py
railway run --service btc-signal-bot python -m telegram_control
```
Stop: Ctrl+C / SIGTERM. Engine paper-ledger state is in-memory (restart
resets the paper day); Postgres state (engine_state, risk params,
ledger/telemetry history) persists.

Railway deployment: one service per process (engine = current `worker`
Procfile; guardian and control plane get their own services pointing at
the same repo with custom start commands). Decision NUC-vs-Railway is
still open — see below.

## Engine states

- `ACTIVE` — engine auto-takes gate-approved signals (dry-run in V2).
- `PAUSED` — signals post with Frame A Take/Skip buttons; no auto-entries.
  This is the schema default on first boot.
- `KILLED` — kill switch or guardian hard-flatten fired. **Never
  auto-resets.**

### Recovering from KILLED
1. Understand why: `SELECT * FROM risk_events ORDER BY ts DESC LIMIT 10;`
2. Confirm positions/orders are actually flat (`/dashboard`, or Propr app).
3. In Telegram: `/run confirm` (a bare `/run` is refused by design).

## Reading logs
- Each process logs to stdout: `alive:` lines (engine), guardian
  connect/threshold warnings, control-plane auth rejections.
- Postgres is the system of record: `risk_events` (every trip, halt,
  kill, param change, floor-guard block), `trade_execution_ledger`
  (every intent with dry_run flag and indicators snapshot),
  `portfolio_telemetry` (equity curve).

## Layered risk defense (all verified by tests)
1. In-process: pre-trade gate (R:R ≥ 2:1, attenuated sizing, worst-case
   floor+$500 clearance, concurrency, venue min) + circuit breaker
   (−2.5% daily, hard-coded).
2. Guardian (separate process): soft-halt floor+$500 → PAUSED;
   hard-flatten floor+$200 → kill sequence + KILLED.
3. Postgres floor-guard trigger: BEFORE INSERT on order intents, blocks
   entries whose worst case crosses binding floor+$200. Fires even if
   layers 1–2 are buggy; never blocks risk-reducing intents.

## Go-live checklist (REQUIRES explicit user instruction — not before)
- [ ] $100K Gold 1-Step Classic challenge purchased; active attempt exists
- [ ] Re-run `scripts/verify_propr_readonly.py` — verify accountId,
      `GET /accounts/{id}` equity fields, `highWaterMark` semantics
      (docstring says highest *balance*, not equity — confirm before
      trusting it as attenuation's peak input)
- [ ] `breakEvenPrice` observed on a real position (SL→Breakeven depends on it)
- [ ] Kill sequence verified against a beta account (live key does NOT
      work on beta — needs separate beta credentials) or accepted risk
      documented
- [ ] Strategy confidence criteria met (user-defined; dry-run ledger
      provides the evidence)
- [ ] Admin allowlist set and control plane tested by each admin
- [ ] Flip switch 2 (`execution_enabled: true`), deploy, verify logs show
      "LIVE EXECUTION ARMED" is still absent (env still dry)
- [ ] Flip switch 1 (`DRY_RUN=false`) as the final deliberate action

## Deployment decision (open): NUC vs Railway
- **Railway**: 3 services + existing Postgres; everything already wired
  (`railway up`, per-service start commands). Guardian isolation = separate
  service. No hardware to babysit.
- **NUC**: install Postgres locally, run 3 processes under systemd (unit
  files: `ExecStart` per entrypoint above, `Restart=always`,
  `EnvironmentFile=/etc/btc-signal-bot.env`); DATABASE_URL points at
  localhost. Lower latency is irrelevant for a 1H system — choose on
  operational preference.

## Open items (carried from build)
1. Admin allowlist IDs not yet supplied — control plane boots locked.
2. Builder code active on all requests; rotate/regenerate in app Settings
   if compromised.
3. `highWaterMark` semantics + `breakEvenPrice` — verify at purchase.
4. Beta-env credentials for live kill verification.
5. `obv_sma_period = 20` — still a flagged convention pending sign-off.
6. Alert formats — pending final user approval before locked.
7. Duplicate Railway DB `Postgres-Xa0f` — delete in dashboard (unused).
