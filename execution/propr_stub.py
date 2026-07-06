"""Stage 2 execution interface stub. Stage 1 contains NO code path that

can place an order — every method here raises NotImplementedError.

Method shapes are drawn from the confirmed Propr API endpoints in
docs/RESEARCH_FINDINGS.md section 3.1 (POST/GET /accounts/{accountId}/orders,
GET /accounts/{accountId}/positions). The account-equity endpoint is
unconfirmed (see RESEARCH_FINDINGS "Needs manual confirmation" #1) so
`get_equity` intentionally has no real endpoint mapped yet.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderIntent:
    account_id: str
    asset: str
    quantity: float
    side: str  # "buy" or "sell"
    order_type: str  # e.g. "market"
    position_side: str  # "long" or "short"


class ProprExecutionStub:
    """Interface only. Every method raises NotImplementedError in Stage 1."""

    def __init__(self, account_id: str, api_key: str | None = None):
        self.account_id = account_id
        self.api_key = api_key

    def place_order(self, intent: OrderIntent) -> None:
        raise NotImplementedError(
            "Stage 1 is signal-only. Order placement (POST /accounts/{accountId}/orders) "
            "is intentionally not implemented."
        )

    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError(
            "Stage 1 is signal-only. Order cancellation "
            "(POST /accounts/{accountId}/orders/{orderId}/cancel) is intentionally not implemented."
        )

    def get_positions(self) -> None:
        raise NotImplementedError(
            "Stage 1 uses the hypothetical ledger/tracker.py, not live Propr positions "
            "(GET /accounts/{accountId}/positions)."
        )

    def get_equity(self) -> None:
        raise NotImplementedError(
            "No confirmed Propr endpoint for live account equity — see "
            "docs/RESEARCH_FINDINGS.md 'Needs manual confirmation' item 1. "
            "Must be resolved before Stage 2 implements this method."
        )
