"""Guardian — independent OS process (V2 build report section 6.2).

Watches the Propr WS equity stream and enforces two buffers above the
binding floor (= max(day-start − $3,000, $94,000), both verified live):

- SOFT-HALT  floor + $500: no new entries (engine_state -> PAUSED)
- HARD-FLATTEN floor + $200: executes the kill sequence autonomously
  (honors DRY_RUN) and locks engine_state -> KILLED

KILLED never auto-resets — recovery requires an explicit /run confirm
through the control plane (Phase 5). Run as its own entrypoint:

    python guardian.py

It shares nothing in-process with the engine; coordination happens only
through Postgres engine_state and its own Propr credentials.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone

logger = logging.getLogger("guardian")

from risk.challenge import DEFAULT_CONFIG, ChallengeConfig, binding_floor as _binding_floor

SOFT_BUFFER_USD = 500.0
HARD_BUFFER_USD = 200.0
TELEMETRY_THROTTLE_SECONDS = 5.0
RECONNECT_DELAY_SECONDS = 5.0


def equity_from_account_event(data: dict) -> float | None:
    """Equity = balance + totalUnrealizedPnl + isolatedPositionMargin
    (SDK docstring — unverified live until the challenge is purchased;
    missing fields are treated as a feed problem, never silently zeroed)."""
    try:
        balance = float(data["balance"])
    except (KeyError, TypeError, ValueError):
        logger.warning("account.updated event missing/invalid balance: keys=%s", sorted(data.keys()))
        return None
    upnl = float(data.get("totalUnrealizedPnl") or 0)
    iso_margin = float(data.get("isolatedPositionMargin") or 0)
    return balance + upnl + iso_margin


@dataclass
class Guardian:
    """Pure decision core — driven by on_equity(); no I/O of its own beyond
    the injected store/execution/telegram collaborators."""

    store: object            # db.store.TelemetryStore-compatible
    execution: object        # execution.propr_client.ProprExecutionService-compatible
    day_start_equity: float
    telegram: object | None = None  # alerts.telegram.TelegramClient-compatible
    soft_halted: bool = False
    flattened: bool = False
    current_day: date | None = None
    # Tier parameterization (risk/challenge.py): defaults reproduce the
    # historical static floors exactly. `hwm` is the persisted high-water
    # mark cache — refreshed from DB at boot, ratcheted locally per event,
    # persisted (throttled with telemetry) so a trailing floor never
    # depends on process memory.
    challenge_cfg: ChallengeConfig = DEFAULT_CONFIG
    hwm: float | None = None

    def binding_floor(self) -> float:
        return _binding_floor(self.challenge_cfg, self.day_start_equity, self.hwm)

    def observe_hwm(self, equity: float) -> None:
        """Local monotonic ratchet; persistence happens with the telemetry
        throttle in the run loop (store.update_hwm)."""
        if self.hwm is None or equity > self.hwm:
            self.hwm = equity

    def _notify(self, text: str) -> None:
        if self.telegram is not None:
            try:
                self.telegram.send(text)
            except Exception:
                logger.warning("guardian telegram notify failed", exc_info=True)

    def on_equity(self, equity: float, now: datetime | None = None) -> list[str]:
        """Evaluate buffers. Returns the actions taken (for tests/logs).

        Hard check runs FIRST: a gap straight through both buffers must
        flatten immediately, not merely soft-halt.
        """
        now = now or datetime.now(timezone.utc)
        self._maybe_rollover(now)
        floor = self.binding_floor()
        actions: list[str] = []

        if not self.flattened and equity <= floor + HARD_BUFFER_USD:
            logger.warning("HARD-FLATTEN: equity %.2f <= floor %.2f + %.0f", equity, floor, HARD_BUFFER_USD)
            result = self.execution.kill_sequence()
            self.store.set_engine_state("KILLED", "guardian")
            self.store.record_risk_event("guardian_hard_flatten", {
                "equity": equity, "binding_floor": floor, "dry_run": result.get("dry_run"),
                "cancelled": len(result.get("cancelled_order_ids", [])),
                "closed": len(result.get("closed", [])),
            })
            self._notify(
                "\U0001F6A8 GUARDIAN HARD-FLATTEN\n"
                f"Equity ${equity:,.2f} within ${HARD_BUFFER_USD:.0f} of binding floor ${floor:,.2f}.\n"
                f"Kill sequence executed (dry_run={result.get('dry_run')}). State locked KILLED — "
                "requires /run confirm to reactivate."
            )
            self.flattened = True
            self.soft_halted = True
            actions.append("hard_flatten")
            return actions

        if not self.soft_halted and equity <= floor + SOFT_BUFFER_USD:
            logger.warning("SOFT-HALT: equity %.2f <= floor %.2f + %.0f", equity, floor, SOFT_BUFFER_USD)
            if self.store.get_engine_state() == "ACTIVE":
                self.store.set_engine_state("PAUSED", "guardian")
            self.store.record_risk_event("guardian_soft_halt", {"equity": equity, "binding_floor": floor})
            self._notify(
                "\U0001F6A8 GUARDIAN SOFT-HALT\n"
                f"Equity ${equity:,.2f} within ${SOFT_BUFFER_USD:.0f} of binding floor ${floor:,.2f}.\n"
                "New entries paused. Existing positions/brackets remain managed."
            )
            self.soft_halted = True
            actions.append("soft_halt")

        return actions

    def _maybe_rollover(self, now: datetime) -> None:
        today = now.date()
        if self.current_day is None:
            self.current_day = today
            return
        if today > self.current_day:
            self.current_day = today
            # soft-halt re-arms daily (daily floor resets); KILLED never
            # auto-resets — that requires an explicit /run confirm.
            self.soft_halted = self.flattened
            logger.info("guardian day rollover: soft-halt re-armed (flattened=%s)", self.flattened)

    def set_day_start(self, equity: float) -> None:
        self.day_start_equity = equity


async def run_ws_loop(guardian: Guardian, execution) -> None:
    """WS watch loop with REST fallback on malformed events."""
    import websockets

    ws_url = os.environ.get("PROPR_WS_URL", "wss://api.propr.xyz/ws")
    headers = {"X-API-Key": os.environ["PROPR_API_KEY"]}
    if os.environ.get("PROPR_BUILDER_CODE"):
        headers["X-Builder-Code"] = os.environ["PROPR_BUILDER_CODE"]

    last_telemetry = 0.0
    while True:
        try:
            async with websockets.connect(ws_url, additional_headers=headers,
                                          ping_interval=20, ping_timeout=10) as ws:
                logger.info("guardian connected to %s", ws_url)
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") not in ("account.updated", "position.updated"):
                        continue

                    equity = equity_from_account_event(msg.get("data", {}))
                    if equity is None:
                        try:
                            acct = execution.get_account()
                            data = acct.get("data", acct)
                            equity = equity_from_account_event(data)
                        except Exception:
                            logger.warning("REST equity fallback failed", exc_info=True)
                    if equity is None:
                        continue

                    guardian.observe_hwm(equity)
                    guardian.on_equity(equity)

                    now_ts = asyncio.get_event_loop().time()
                    if now_ts - last_telemetry >= TELEMETRY_THROTTLE_SECONDS:
                        # Persist the HWM ratchet with the same throttle; the
                        # DB GREATEST makes double-writes/no-ops harmless.
                        guardian.hwm = guardian.store.update_hwm(equity)
                        guardian.store.record_telemetry(
                            equity=equity,
                            day_start_equity=guardian.day_start_equity,
                            engine_state=guardian.store.get_engine_state(),
                        )
                        last_telemetry = now_ts
        except Exception:
            logger.warning("guardian WS loop error — reconnecting in %ss",
                           RECONNECT_DELAY_SECONDS, exc_info=True)
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    import yaml

    from alerts.telegram import TelegramClient
    from db.store import TelemetryStore
    from execution.propr_client import ProprExecutionService

    store = TelemetryStore()
    store.apply_schema()
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    execution = ProprExecutionService(
        # Same two-switch rule as the engine: live flatten requires BOTH
        # DRY_RUN=false AND execution_enabled true. All of V2 runs dry.
        execution_enabled=bool(cfg.get("feature_flags", {}).get("execution_enabled", False)),
    )
    execution.setup()
    acct = execution.get_account()
    data = acct.get("data", acct)
    equity = equity_from_account_event(data)
    if equity is None:
        raise RuntimeError("cannot establish starting equity from Propr account — refusing to guard blind")

    guardian = Guardian(store=store, execution=execution, day_start_equity=equity,
                        telegram=TelegramClient(),
                        challenge_cfg=store.get_challenge_config(),
                        hwm=store.update_hwm(equity))
    logger.info("guardian starting: day_start_equity=%.2f binding_floor=%.2f "
                "(tier=%s dd=%.1f%% daily=%.1f%% hwm=%.2f)",
                equity, guardian.binding_floor(), guardian.challenge_cfg.drawdown_type,
                guardian.challenge_cfg.max_drawdown_pct,
                guardian.challenge_cfg.daily_loss_pct, guardian.hwm)
    asyncio.run(run_ws_loop(guardian, execution))


if __name__ == "__main__":
    main()
