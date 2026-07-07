"""Propr execution service — Stage 2, dry-run by default.

Wraps the vendored official SDK (execution/vendor/propr_sdk.py, pinned to
propr-docs @ fee88098) with:

1. A HARD dry-run gate on every write-capable method. Dry-run is the
   default; going live requires BOTH `DRY_RUN=false` (env) AND
   `execution_enabled: true` (config feature flag) — two independent
   switches. In dry-run, intents are recorded and logged, never sent.
2. `X-Builder-Code` header on all requests (propr.xyz/developers —
   identifies this bot as a legitimate integration).
3. Order mechanics per docs/RESEARCH_FINDINGS.md Rev 3: string
   quantities/Decimal math, intentId ULID idempotency, 200/201 both
   success, reduceOnly on every reducing order, batch bracket orders
   under one orderGroupId, kill sequence via enumerate-and-cancel (no
   server-side bulk cancel exists).

Strategy/risk/ledger modules must NOT import this module (build spec
module firewall) — the engine wires it in as a consumer of signals.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from ulid import ULID

from execution.vendor.propr_sdk import ProprClient

logger = logging.getLogger(__name__)

BTC_MIN_QUANTITY = Decimal("0.001")  # verified: api.md Available Assets table


def _env_dry_run() -> bool:
    """DRY_RUN env var: anything other than the literal string 'false' means dry-run."""
    return os.environ.get("DRY_RUN", "true").strip().lower() != "false"


@dataclass(frozen=True)
class OrderIntent:
    """What we would send (or sent) to Propr — the unit of the audit ledger."""
    intent_id: str
    asset: str
    side: str  # "buy" | "sell"
    position_side: str  # "long" | "short"
    order_type: str  # market | limit | stop_market | take_profit_market | ...
    quantity: str  # string, venue-step truncated upstream
    time_in_force: str
    price: str | None = None
    trigger_price: str | None = None
    reduce_only: bool = False
    close_position: bool = False
    order_group_id: str | None = None
    position_id: str | None = None  # required for standalone conditionals (api.md batch rules)
    purpose: str = ""  # human tag: "entry", "stop_loss", "take_profit", "kill_close", ...
    # Risk context, set on ENTRY intents only — consumed by the Postgres
    # floor-guard trigger (worst-case = |entry - stop| * quantity).
    risk_entry_price: str | None = None
    risk_stop_price: str | None = None


@dataclass(frozen=True)
class DispatchResult:
    dry_run: bool
    intents: list[OrderIntent]
    responses: list[dict] = field(default_factory=list)  # empty in dry-run


class ProprExecutionService:
    """All Propr access for the bot. Reads pass through; writes are gated."""

    def __init__(
        self,
        api_key: str | None = None,
        builder_code: str | None = None,
        base_url: str | None = None,
        execution_enabled: bool = False,
        account_id: str | None = None,
        intent_sink: Callable[[OrderIntent], None] | None = None,
    ):
        self._client = ProprClient(api_key=api_key, base_url=base_url)
        self.builder_code = builder_code or os.environ.get("PROPR_BUILDER_CODE")
        if self.builder_code:
            self._client._session.headers["X-Builder-Code"] = self.builder_code
        if account_id:
            self._client.account_id = account_id

        # Two-switch arming: BOTH must open for live dispatch.
        env_dry = _env_dry_run()
        self.dry_run = env_dry or not execution_enabled
        self._intent_sink = intent_sink

        if self.dry_run:
            logger.info(
                "ProprExecutionService in DRY-RUN mode (env_dry_run=%s, execution_enabled=%s) — no orders will be dispatched",
                env_dry, execution_enabled,
            )
        else:
            logger.warning("ProprExecutionService LIVE EXECUTION ARMED — real orders WILL be dispatched")

    # ── reads (pass-through, always allowed) ──

    def setup(self, account_id: str | None = None) -> str:
        return self._client.setup(account_id=account_id)

    def health_ok(self) -> bool:
        try:
            services = self._client.health_services()
            return all(v == "OK" for v in services.values())
        except Exception:
            logger.warning("Propr health check failed", exc_info=True)
            return False

    def get_account(self) -> dict:
        return self._client.get_account()

    def get_open_positions(self, base: str | None = None) -> list[dict]:
        return self._client.get_open_positions(base=base)

    def get_open_orders(self, base: str | None = None) -> list[dict]:
        return self._client.get_orders(status="open", base=base)

    def get_trades(self, **kwargs) -> list[dict]:
        return self._client.get_trades(**kwargs)

    def max_leverage(self, asset: str) -> int:
        """Shape-safe leverage lookup (RESEARCH_FINDINGS Rev 3 drift #2).

        Live API returns per-asset-class `defaults`; older docs/SDK expect
        scalar `defaultMax`. Handle both, warn if neither is present.
        """
        limits = self._client.get_leverage_limits()
        overrides = limits.get("overrides", {})
        if asset in overrides:
            return int(overrides[asset])
        if "defaultMax" in limits:
            return int(limits["defaultMax"])
        defaults = limits.get("defaults", {})
        if "crypto" in defaults:
            return int(defaults["crypto"])
        logger.warning("Unrecognized leverage-limits shape %s — defaulting to 1x", sorted(limits.keys()))
        return 1

    # ── writes (dry-run gated) ──

    def _record(self, intent: OrderIntent) -> None:
        if self._intent_sink is not None:
            # Phase 3 wires the Postgres intent writer here; its BEFORE
            # INSERT trigger is the last line of defense and fires even in
            # dry-run, because recording precedes dispatch.
            self._intent_sink(intent)
        logger.info("%s intent: %s %s %s qty=%s purpose=%s",
                    "[DRY-RUN]" if self.dry_run else "[LIVE]",
                    intent.order_type, intent.side, intent.asset, intent.quantity, intent.purpose)

    def _intent_to_wire(self, intent: OrderIntent) -> dict:
        order: dict = {
            "accountId": self._client.account_id,
            "intentId": intent.intent_id,
            "exchange": "hyperliquid",
            "type": intent.order_type,
            "side": intent.side,
            "positionSide": intent.position_side,
            "productType": "perp",
            "timeInForce": intent.time_in_force,
            "asset": intent.asset,
            "base": intent.asset,
            "quote": "USDC",
            "quantity": intent.quantity,
            "reduceOnly": intent.reduce_only,
            "closePosition": intent.close_position,
        }
        if intent.price is not None:
            order["price"] = intent.price
        if intent.trigger_price is not None:
            order["triggerPrice"] = intent.trigger_price
        if intent.position_id is not None:
            order["positionId"] = intent.position_id
        return order

    def _dispatch(self, intents: list[OrderIntent]) -> DispatchResult:
        for intent in intents:
            self._record(intent)
        if self.dry_run:
            return DispatchResult(dry_run=True, intents=intents)

        payload: dict = {"orders": [self._intent_to_wire(i) for i in intents]}
        if len(intents) > 1:
            # Verified batch rule: orderGroupId required when orders.length > 1
            group_id = intents[0].order_group_id or str(ULID())
            payload["orderGroupId"] = group_id
        resp = self._client._post(self._client._account_path("/orders"), json=payload)
        return DispatchResult(dry_run=False, intents=intents, responses=resp.get("data", []))

    def create_entry_with_bracket(
        self,
        direction: str,  # "long" | "short"
        quantity: str,
        stop_trigger: str,
        target_trigger: str,
        entry_ref_price: str | None = None,
    ) -> DispatchResult:
        """Market entry + stop_market SL + take_profit_market TP in one
        batch under a shared orderGroupId (verified batch rules: one entry
        per request; conditionals valid when grouped with the entry).

        entry_ref_price: the signal's entry reference (last close) — market
        entries have no limit price, so the floor-guard trigger uses this
        for its worst-case computation.
        """
        if Decimal(quantity) < BTC_MIN_QUANTITY:
            raise ValueError(f"quantity {quantity} below venue minimum {BTC_MIN_QUANTITY}")

        group_id = str(ULID())
        entry_side = "buy" if direction == "long" else "sell"
        exit_side = "sell" if direction == "long" else "buy"

        intents = [
            OrderIntent(
                intent_id=str(ULID()), asset="BTC", side=entry_side, position_side=direction,
                order_type="market", quantity=quantity, time_in_force="IOC",
                order_group_id=group_id, purpose="entry",
                risk_entry_price=entry_ref_price, risk_stop_price=stop_trigger,
            ),
            OrderIntent(
                intent_id=str(ULID()), asset="BTC", side=exit_side, position_side=direction,
                order_type="stop_market", quantity=quantity, time_in_force="GTC",
                trigger_price=stop_trigger, reduce_only=True,
                order_group_id=group_id, purpose="stop_loss",
            ),
            OrderIntent(
                intent_id=str(ULID()), asset="BTC", side=exit_side, position_side=direction,
                order_type="take_profit_market", quantity=quantity, time_in_force="GTC",
                trigger_price=target_trigger, reduce_only=True,
                order_group_id=group_id, purpose="take_profit",
            ),
        ]
        return self._dispatch(intents)

    def close_position_market(self, position: dict, fraction: Decimal = Decimal("1"), purpose: str = "close") -> DispatchResult:
        """Reduce/close a position by fraction (market IOC, reduceOnly)."""
        qty = Decimal(position["quantity"]) * fraction
        qty_str = str(qty.quantize(BTC_MIN_QUANTITY))
        direction = position["positionSide"]
        close_side = "sell" if direction == "long" else "buy"
        full_close = fraction == Decimal("1")

        intent = OrderIntent(
            intent_id=str(ULID()), asset=position.get("base", "BTC"), side=close_side,
            position_side=direction, order_type="market", quantity=qty_str,
            time_in_force="IOC", reduce_only=True, close_position=full_close,
            purpose=purpose,
        )
        return self._dispatch([intent])

    def move_stop_to(self, position: dict, trigger_price: str) -> DispatchResult:
        """Replace the position's stop: cancel existing stop_market orders
        linked to it, then place a fresh reduceOnly stop at trigger_price
        (standalone conditional with positionId — verified valid shape)."""
        position_id = position.get("positionId")
        for order in self.get_open_orders(base=position.get("base", "BTC")):
            if order.get("positionId") == position_id and order.get("type") == "stop_market":
                self.cancel_order(order["orderId"])

        direction = position["positionSide"]
        exit_side = "sell" if direction == "long" else "buy"
        intent = OrderIntent(
            intent_id=str(ULID()), asset=position.get("base", "BTC"), side=exit_side,
            position_side=direction, order_type="stop_market",
            quantity=str(position["quantity"]), time_in_force="GTC",
            trigger_price=trigger_price, reduce_only=True,
            position_id=position_id, purpose="stop_move",
        )
        return self._dispatch([intent])

    def cancel_order(self, order_id: str) -> bool:
        """Cancel one order. 200/201 = success; 400 = already done (True)."""
        intent = OrderIntent(
            intent_id=str(ULID()), asset="BTC", side="-", position_side="-",
            order_type="cancel", quantity="0", time_in_force="-", purpose=f"cancel:{order_id}",
        )
        self._record(intent)
        if self.dry_run:
            return True
        result = self._client.cancel_order(order_id)  # SDK maps 400 -> None
        return True  # both cancelled and already-done are success per docs

    def kill_sequence(self) -> dict:
        """Prop Saver: cancel every resting order, then market-close every
        open position (reduceOnly + closePosition, IOC). No server-side
        bulk cancel exists — enumerate and act per item (verified).
        Honors dry-run: in dry-run, records intents and dispatches nothing.
        """
        cancelled_ids: list[str] = []
        for order in self.get_open_orders():
            order_id = order["orderId"]
            self.cancel_order(order_id)
            cancelled_ids.append(order_id)

        closed: list[DispatchResult] = []
        for pos in self.get_open_positions():
            closed.append(self.close_position_market(pos, purpose="kill_close"))

        logger.warning(
            "KILL SEQUENCE executed (dry_run=%s): %d orders cancelled, %d positions closed",
            self.dry_run, len(cancelled_ids), len(closed),
        )
        return {"dry_run": self.dry_run, "cancelled_order_ids": cancelled_ids, "closed": closed}
