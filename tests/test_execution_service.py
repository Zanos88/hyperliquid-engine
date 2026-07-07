"""Phase 1 acceptance tests: execution service against a fake HTTP session.

No network access anywhere in this file — the vendored SDK's session is
replaced with a recorder. These tests are the proof that:
- dry-run blocks dispatch (zero HTTP writes),
- the two-switch arming rule holds,
- X-Builder-Code is present on outgoing requests,
- batch/bracket, cancel, and kill-sequence mechanics match the verified
  Propr API rules (RESEARCH_FINDINGS Rev 3).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from execution.propr_client import BTC_MIN_QUANTITY, OrderIntent, ProprExecutionService


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"data": []}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    """Stands in for requests.Session inside the vendored SDK."""

    def __init__(self):
        self.headers: dict = {}
        self.calls: list[dict] = []
        self.routes: list[tuple[str, str, FakeResponse]] = []  # (method, url_substring, response)

    def route(self, method: str, url_contains: str, response: FakeResponse):
        self.routes.append((method.upper(), url_contains, response))

    def request(self, method, url, params=None, json=None, timeout=None):
        self.calls.append({
            "method": method.upper(), "url": url, "params": params, "json": json,
            "headers": dict(self.headers),
        })
        for m, fragment, resp in self.routes:
            if m == method.upper() and fragment in url:
                return resp
        return FakeResponse()

    def writes(self) -> list[dict]:
        return [c for c in self.calls if c["method"] in ("POST", "PUT", "DELETE", "PATCH")]


def make_service(monkeypatch, dry_env: str | None, execution_enabled: bool,
                 sink=None) -> tuple[ProprExecutionService, FakeSession]:
    if dry_env is None:
        monkeypatch.delenv("DRY_RUN", raising=False)
    else:
        monkeypatch.setenv("DRY_RUN", dry_env)
    monkeypatch.setenv("PROPR_BUILDER_CODE", "builder_testcode12345")

    svc = ProprExecutionService(
        api_key="pk_live_TESTKEY", execution_enabled=execution_enabled,
        account_id="urn:prp-account:TEST", intent_sink=sink,
    )
    fake = FakeSession()
    fake.headers = dict(svc._client._session.headers)  # keep auth + builder headers
    svc._client._session = fake
    return svc, fake


# ── dry-run gating ──

def test_dry_run_is_default_and_blocks_dispatch(monkeypatch):
    recorded: list[OrderIntent] = []
    svc, fake = make_service(monkeypatch, dry_env=None, execution_enabled=False,
                             sink=recorded.append)
    result = svc.create_entry_with_bracket("long", "0.010", stop_trigger="59000", target_trigger="63000")

    assert svc.dry_run is True
    assert result.dry_run is True
    assert fake.writes() == []            # zero HTTP writes recorded
    assert len(result.intents) == 3       # entry + SL + TP intents still produced
    assert len(recorded) == 3             # sink fires even in dry-run


def test_two_switch_arming_env_false_but_flag_off(monkeypatch):
    svc, fake = make_service(monkeypatch, dry_env="false", execution_enabled=False)
    assert svc.dry_run is True
    svc.create_entry_with_bracket("long", "0.010", "59000", "63000")
    assert fake.writes() == []


def test_two_switch_arming_flag_on_but_env_dry(monkeypatch):
    svc, fake = make_service(monkeypatch, dry_env=None, execution_enabled=True)
    assert svc.dry_run is True
    svc.create_entry_with_bracket("long", "0.010", "59000", "63000")
    assert fake.writes() == []


# ── live-mode mechanics (both switches open, fake HTTP) ──

def test_live_bracket_batch_shape_and_builder_header(monkeypatch):
    svc, fake = make_service(monkeypatch, dry_env="false", execution_enabled=True)
    fake.route("POST", "/orders", FakeResponse(201, {"data": [{"orderId": "o1"}, {"orderId": "o2"}, {"orderId": "o3"}]}))

    result = svc.create_entry_with_bracket("long", "0.010", stop_trigger="59000", target_trigger="63000")

    writes = fake.writes()
    assert len(writes) == 1
    call = writes[0]
    assert call["headers"].get("X-Builder-Code") == "builder_testcode12345"
    assert call["headers"].get("X-API-Key") == "pk_live_TESTKEY"

    body = call["json"]
    assert "orderGroupId" in body                    # required: orders.length > 1
    orders = body["orders"]
    assert len(orders) == 3
    entry, sl, tp = orders
    assert entry["type"] == "market" and entry["timeInForce"] == "IOC" and entry["side"] == "buy"
    assert sl["type"] == "stop_market" and sl["reduceOnly"] is True and sl["triggerPrice"] == "59000"
    assert tp["type"] == "take_profit_market" and tp["reduceOnly"] is True and tp["triggerPrice"] == "63000"
    assert all(isinstance(o["quantity"], str) for o in orders)   # string money
    assert all(o["intentId"] for o in orders)                    # ULIDs present
    assert result.dry_run is False and len(result.responses) == 3


def test_quantity_below_venue_minimum_rejected(monkeypatch):
    svc, _ = make_service(monkeypatch, dry_env=None, execution_enabled=False)
    with pytest.raises(ValueError):
        svc.create_entry_with_bracket("long", "0.0001", "59000", "63000")
    assert Decimal("0.001") == BTC_MIN_QUANTITY


def test_cancel_accepts_200_201_and_400_as_done(monkeypatch):
    svc, fake = make_service(monkeypatch, dry_env="false", execution_enabled=True)
    fake.route("POST", "/cancel", FakeResponse(201, {"orderId": "x"}))
    assert svc.cancel_order("urn:prp-order:A") is True

    fake.routes.clear()
    fake.route("POST", "/cancel", FakeResponse(400, {"code": 400, "message": "already filled"}))
    assert svc.cancel_order("urn:prp-order:B") is True   # already done == success


def test_kill_sequence_live(monkeypatch):
    svc, fake = make_service(monkeypatch, dry_env="false", execution_enabled=True)
    fake.route("GET", "/orders", FakeResponse(200, {"data": [
        {"orderId": "urn:prp-order:O1"}, {"orderId": "urn:prp-order:O2"},
    ]}))
    fake.route("GET", "/positions", FakeResponse(200, {"data": [
        {"positionId": "urn:prp-position:P1", "positionSide": "long", "quantity": "0.500", "base": "BTC"},
    ]}))
    fake.route("POST", "/cancel", FakeResponse(201, {}))
    fake.route("POST", "/orders", FakeResponse(201, {"data": [{"orderId": "close1"}]}))

    result = svc.kill_sequence()

    assert result["dry_run"] is False
    assert result["cancelled_order_ids"] == ["urn:prp-order:O1", "urn:prp-order:O2"]
    close_posts = [c for c in fake.writes() if c["url"].endswith("/orders") and c["json"]]
    assert len(close_posts) == 1
    close_order = close_posts[0]["json"]["orders"][0]
    assert close_order["side"] == "sell" and close_order["reduceOnly"] is True
    assert close_order["closePosition"] is True and close_order["timeInForce"] == "IOC"
    assert close_order["type"] == "market" and close_order["quantity"] == "0.500"


def test_kill_sequence_dry_run_reads_but_never_writes(monkeypatch):
    svc, fake = make_service(monkeypatch, dry_env=None, execution_enabled=False)
    fake.route("GET", "/orders", FakeResponse(200, {"data": [{"orderId": "urn:prp-order:O1"}]}))
    fake.route("GET", "/positions", FakeResponse(200, {"data": [
        {"positionId": "urn:prp-position:P1", "positionSide": "short", "quantity": "0.250", "base": "BTC"},
    ]}))

    result = svc.kill_sequence()

    assert result["dry_run"] is True
    assert result["cancelled_order_ids"] == ["urn:prp-order:O1"]   # recorded as intents
    assert fake.writes() == []                                      # nothing dispatched


# ── leverage-limits shape drift (Rev 3 finding #2) ──

def test_max_leverage_new_per_class_shape(monkeypatch):
    svc, fake = make_service(monkeypatch, dry_env=None, execution_enabled=False)
    fake.route("GET", "/leverage-limits/effective", FakeResponse(200, {
        "defaults": {"crypto": 2, "equity": 4, "fx": 25}, "overrides": {"BTC": 5, "ETH": 5},
    }))
    assert svc.max_leverage("BTC") == 5
    assert svc.max_leverage("SOL") == 2   # falls back to defaults.crypto


def test_max_leverage_old_documented_shape(monkeypatch):
    svc, fake = make_service(monkeypatch, dry_env=None, execution_enabled=False)
    fake.route("GET", "/leverage-limits/effective", FakeResponse(200, {
        "defaultMax": 2, "overrides": {"BTC": 5},
    }))
    assert svc.max_leverage("BTC") == 5
    assert svc.max_leverage("SOL") == 2
