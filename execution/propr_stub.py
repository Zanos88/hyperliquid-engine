"""Stage 2 execution interface stub. Stage 1 contains NO code path that
can place an order — every method here raises NotImplementedError.

Method names/signatures match the verified Propr Python SDK
(`python/propr_sdk.py` in github.com/XBorgLabs/propr-docs — see
docs/RESEARCH_FINDINGS.md section 3.1) so Stage 2 can swap this stub for
the real SDK with no interface change: `setup`, `get_account`,
`create_order`, `get_open_positions`, `close_position`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderIntent:
    account_id: str
    asset: str
    quantity: float
    side: str  # "buy" or "sell"
    order_type: str  # "market" | "limit" | "stop_market" | "take_profit_market"
    position_side: str  # "long" or "short"
    time_in_force: str = "GTC"  # "IOC" | "GTC"
    reduce_only: bool = False


class ProprExecutionStub:
    """Interface only. Every method raises NotImplementedError in Stage 1."""

    def __init__(self, account_id: str, api_key: str | None = None):
        self.account_id = account_id
        self.api_key = api_key

    def setup(self) -> None:
        raise NotImplementedError(
            "Stage 1 is signal-only. Client/session setup (auth via X-API-Key, "
            "account discovery via GET /challenge-attempts?status=active) is "
            "intentionally not implemented."
        )

    def get_account(self) -> None:
        raise NotImplementedError(
            "Stage 1 uses the hypothetical ledger/tracker.py for equity, not live "
            "Propr account state (GET /accounts/{accountId} -> balance, "
            "availableBalance, totalUnrealizedPnl, marginBalance, highWaterMark; "
            "equity = balance + totalUnrealizedPnl + isolatedPositionMargin per "
            "the SDK docstring — see docs/RESEARCH_FINDINGS.md 3.1)."
        )

    def create_order(self, intent: OrderIntent) -> None:
        raise NotImplementedError(
            "Stage 1 is signal-only. Order placement "
            "(POST /accounts/{accountId}/orders, batch array, 201 on create) "
            "is intentionally not implemented."
        )

    def get_open_positions(self) -> None:
        raise NotImplementedError(
            "Stage 1 uses the hypothetical ledger/tracker.py, not live Propr "
            "positions (GET /accounts/{accountId}/positions)."
        )

    def close_position(self, position_id: str) -> None:
        raise NotImplementedError(
            "Stage 1 is signal-only. Closing a position "
            "(order with reduceOnly/closePosition) is intentionally not implemented."
        )
