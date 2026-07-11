# Gold 2-Step Re-Parameterization — Step 0 (tier verification) + Step 1 (audit) + Sizing Study

Date: 2026-07-11. Executes the staged build spec (uploaded
GOLD_2STEP_REPARAMETERIZATION.md) through its report-before-build gate.
**Steps 2–3 (parameterized floors, HWM tracker, stress tests) are NOT
built yet** — per the spec, they start only after this report is reviewed.

## Step 0 — tier parameters verified against Propr's API (primary source)

`GET /challenges` (X-API-Key auth), challenge `gold-t`
(`urn:prp-challenge:WeD1X2XxmB2X`, 100,000 USDC):

| Phase (API `order`) | Profit target | Daily loss | Max drawdown | Type |
|---|---|---|---|---|
| Phase 1 | **5%** | 5% | 8% | **trailing** |
| Phase 2 | **10%** | 5% | 8% | **trailing** |

- **Discrepancy flagged:** the purchase-screen screenshot displays
  "Profit target 10% → 5%"; the API's phase order says 5% first, then
  10% (cumulative +15.5% compounded to clear both). Confirm the display
  order in the app — the API is treated as primary here.
- **Open item (as the spec predicted):** the API exposes only the
  percentages. Trailing-floor mechanics — continuous vs interval
  recalculation, and whether the HWM is equity-based or balance-based —
  are NOT exposed. This requires a direct question to Propr before the
  HWM tracker's update rule is finalized; the build will implement the
  conservative reading (continuous, equity-based) unless Propr says
  otherwise.

**Finding that changes the build's initialization step:**
`GET /challenge-attempts?status=active` returns **0 active attempts** on
this API key. There is currently **no live challenge account** behind the
system (consistent with the runbook's unchecked "challenge purchased"
item). Consequences: (a) the spec's "initialize HWM from real account
equity via the account endpoint" cannot run yet — HWM initialization
becomes an activation-time step, with config/paper equity as the staging
placeholder; (b) today's hardcoded floors currently protect a dry-run
paper account only — the reparameterization is still mandatory BEFORE any
real attempt starts, but there is no live-money exposure this minute.

## Step 1 — audit of hardcoded tier assumptions (read-only, complete)

The spec's "four locations" are in fact **nine** (enforcement + schema
constraint + display), all verified in current source:

| # | Site | Hardcode | Layer |
|---|---|---|---|
| 1 | `db/schema.sql` `enforce_floor_guard()` | `GREATEST(day_start−3000, 94000)+200` | ENFORCEMENT (DB trigger) |
| 2 | `guardian.py:31-32` | `DAILY_LOSS_LIMIT_USD=3000`, `STATIC_FLOOR_USD=94000` (+500/+200 buffers) | ENFORCEMENT |
| 3 | `risk/gate.py:7` | binding floor = max(day_start−3000, 94000); worst-case clearance | ENFORCEMENT |
| 4 | `risk/sizing.py:26` | `STATIC_FLOOR_USD=94000` inside the attenuation formula (comment records the OLD tier: "Gold 1-Step … drawdownType=static — VERIFIED live") | ENFORCEMENT (sizing) |
| 5 | `risk/circuit_breaker.py:13` | `HALT_THRESHOLD_PCT=−2.5%` — chosen as a buffer inside the old 3% daily | ENFORCEMENT |
| 6 | `db/schema.sql` `risk_params` CHECK | `risk_pct <= 0.01` — caps sizing at 1% regardless of tier | CONSTRAINT |
| 7 | `db/store.py:86` | telemetry floor-distance columns (−3000 / −94000) | DISPLAY |
| 8 | `alerts/formats.py:25`, `telegram_control/handlers.py:175` | dd_left = equity − 94000 | DISPLAY |
| 9 | `web/api/index.py:146,154` | dashboard static_floor/daily_loss | DISPLAY |

Plus `tests/test_gate_and_attenuation.py`, which encodes the old constants
and must become parameterized fixtures. Two design notes the build must
answer (Zane's call, surfaced now): does the −2.5% breaker stay
(conservative) or scale to ~−4% under the 5% daily limit; and does the 1%
risk_pct schema cap stay (the sizing study below shows why it might not).
One favorable discovery: `risk/sizing.py` already consumes a
`peak_equity` input for attenuation — an HWM concept half-exists; the
build persists it to Postgres (the deploy-resets-memory lesson) and
re-anchors attenuation to the trailing floor.

**Entanglement check (spec's stop-condition): none found.** All nine
sites are account-level thresholds; none is entangled with signal logic.

## Sizing study — "$50–80k positions" vs the current architecture

Computed from the corrected 4h/1h baseline's stored trades (8 trades,
209 days; SIMULATED caveats). The system's structural stops are TIGHT —
0.151–0.532% of entry — which drives everything:

**A) Fixed-notional sizing (the $50–80k framing):**

| Notional | 209-day P&L | Annualized | Max DD ($) | Worst trade |
|---|---|---|---|---|
| $50k | +$832 | +1.5%/yr | $328 | −$239 |
| $65k | +$1,082 | +1.9%/yr | $426 | −$311 |
| $80k | +$1,331 | +2.3%/yr | $525 | −$383 |

**B) Risk-based sizing (current architecture), compounded:**

| Risk/trade | Annualized | Max DD | Implied notional (median → max) | Worst single-day |
|---|---|---|---|---|
| 0.75% (live) | +3.6%/yr | 2.77% | $275k → $510k | −1.5% |
| 1.00% (schema cap) | +4.8%/yr | 3.69% | $366k → $685k | −2.0% |
| 1.50% (needs cap change) | +7.1%/yr | 5.50% | $547k → $1.05M | −3.0% |
| 2.00% | +9.2%/yr | **7.30%** | $726k → $1.42M | −4.0% |

**The direct answer: $50–80k positions are a 2–5× DE-risking, not an
increase.** Because stops are 0.15–0.5% tight, the live risk-based sizing
already implies **$275–510k median-to-max notionals at 0.75% risk** —
capping notional at $80k throttles risk to ~0.15–0.38% per trade and
annualized return to ~2%, which can never reach the 5%+10% phase targets.
The lever that exists is risk_pct, and its ladder against the verified
tier: 1.5% is the maximum defensible single-sleeve setting (maxDD 5.50%
vs 8% trailing = 1.45× headroom; worst day 3% vs 5% = 1.7×) — and it
requires relaxing the schema's 1% CHECK. 2% effectively exhausts the
trailing budget (7.30% observed on an n=8 sample) — not defensible.

**Even maxed-out sizing is slow against the targets:** ~+7%/yr at 1.5%
means ~9 months to clear Phase 1's 5% and years for Phase 2 — consistent
with the prior conclusion that **frequency/breadth (multi-asset sleeves),
not per-trade size, is the binding lever** for the 2-Step's profit
targets. Leverage note: implied notionals up to ~$1M on a $100k account
(≈10×) at 1.5% risk — fine for Hyperliquid BTC limits, but whether Propr
imposes per-challenge leverage caps is not exposed in the phase params —
added to the Propr question list.

## Go/no-go recommendation (Step 2–3 build)

**GO — build now, in staging, per the spec** (parameterized dual-shape
floor config; Postgres-persisted HWM tracker with monotonic-up guarantee;
daily 3%→5%; the nine sites + tests), with two spec amendments from
Step 0's findings: (1) HWM initialization from the Propr account endpoint
becomes an activation-time step (no active attempt exists); (2) two
explicit user decisions are packaged into the go/no-go review: breaker
−2.5% vs −4%, and the 1% risk_pct cap vs 1.5%. The Propr trailing-mechanics
question should be asked in parallel — the conservative implementation
does not need to wait for the answer.

No live deploy exists in this plan; Step 4 sign-off gates that, per the
spec, after stress-test results are reviewed with real numbers.
