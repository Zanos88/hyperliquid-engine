"""Phase 0 read-only Propr API verification (V2 build).

STRICTLY READ-ONLY: this script performs GET requests and one WebSocket
subscribe. It contains no POST/PUT/DELETE call of any kind and cannot
place, cancel, or modify anything.

Run with secrets injected from Railway (never pasted into chat/repo):
    railway run python scripts/verify_propr_readonly.py

Security: the API key is never printed; URN identifiers are redacted to
their last 4 characters.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import requests

LIVE_BASE = "https://api.propr.xyz/v1"
BETA_BASE = "https://api.beta.propr.xyz/v1"
LIVE_WS = "wss://api.propr.xyz/ws"

API_KEY = os.environ.get("PROPR_API_KEY")
BUILDER_CODE = os.environ.get("PROPR_BUILDER_CODE")


def redact(value: str | None) -> str:
    if not value:
        return "<none>"
    return f"...{value[-4:]}"


def headers() -> dict:
    h = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    if BUILDER_CODE:
        h["X-Builder-Code"] = BUILDER_CODE
    return h


def get(base: str, path: str, params: dict | None = None) -> tuple[int, dict | list | str]:
    resp = requests.get(f"{base}{path}", headers=headers(), params=params, timeout=15)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text[:200]


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    if not API_KEY:
        sys.exit("PROPR_API_KEY not set — add it as a Railway service variable and run via `railway run`.")
    print(f"key present: yes (redacted {redact(API_KEY)}) | builder code set: {bool(BUILDER_CODE)}")

    section("health (live)")
    print(get(LIVE_BASE, "/health"), get(LIVE_BASE, "/health/services"))

    section("challenges (C2 tier check — now auth-required per drift finding)")
    code, body = get(LIVE_BASE, "/challenges", params={"limit": 50})
    print("status:", code)
    if isinstance(body, dict):
        challenges = body.get("data", [])
        print(f"{len(challenges)} challenges")
        for c in challenges:
            keys = sorted(c.keys())
            print("- name:", c.get("name"), "| keys:", keys)
            print("  full:", json.dumps({k: v for k, v in c.items() if k not in ("description",)}, default=str)[:800])
    else:
        print(body)

    section("challenge-attempts?status=active -> accountId")
    code, body = get(LIVE_BASE, "/challenge-attempts", params={"status": "active"})
    print("status:", code)
    account_id = None
    if isinstance(body, dict):
        attempts = body.get("data", [])
        print(f"{len(attempts)} active attempts")
        for a in attempts:
            account_id = a.get("accountId")
            print("- attempt:", redact(a.get("attemptId")), "| accountId:", redact(account_id),
                  "| status:", a.get("status"), "| keys:", sorted(a.keys()))

    if not account_id:
        print("NO ACTIVE ATTEMPT — account-scoped checks skipped (challenge not purchased yet?)")
    else:
        section("GET /accounts/{accountId} — equity fields")
        code, body = get(LIVE_BASE, f"/accounts/{account_id}")
        print("status:", code)
        if isinstance(body, dict):
            data = body.get("data", body)
            print("field names:", sorted(data.keys()) if isinstance(data, dict) else type(data))
            if isinstance(data, dict):
                for k in ("balance", "availableBalance", "totalUnrealizedPnl", "marginBalance",
                          "crossPositionMargin", "isolatedPositionMargin", "highWaterMark"):
                    print(f"  {k}: {data.get(k)}")

        section("positions (expect none/zero)")
        code, body = get(LIVE_BASE, f"/accounts/{account_id}/positions")
        n = len(body.get("data", [])) if isinstance(body, dict) else "?"
        print("status:", code, "| positions:", n)

        section("orders (open — expect none)")
        code, body = get(LIVE_BASE, f"/accounts/{account_id}/orders", params={"status": "open"})
        n = len(body.get("data", [])) if isinstance(body, dict) else "?"
        print("status:", code, "| open orders:", n)

    section("beta env — same key, read-only")
    print("beta /health:", get(BETA_BASE, "/health"))
    code, body = get(BETA_BASE, "/challenge-attempts", params={"status": "active"})
    print("beta /challenge-attempts status:", code,
          "| attempts:", len(body.get("data", [])) if isinstance(body, dict) else body)

    section("websocket — connect + listen 10s (read-only subscribe)")
    try:
        import websockets

        async def ws_check() -> None:
            extra = {"X-API-Key": API_KEY}
            if BUILDER_CODE:
                extra["X-Builder-Code"] = BUILDER_CODE
            async with websockets.connect(LIVE_WS, additional_headers=extra, ping_interval=20) as ws:
                try:
                    async with asyncio.timeout(10):
                        async for raw in ws:
                            msg = json.loads(raw)
                            data = msg.get("data", {})
                            if isinstance(data, dict) and "userId" in data:
                                data = {**data, "userId": redact(data["userId"])}
                            print("ws event:", msg.get("type"), "| data keys:",
                                  sorted(data.keys()) if isinstance(data, dict) else data)
                            if msg.get("type") == "connected":
                                print("  (connected OK — continuing to listen for stray events)")
                except TimeoutError:
                    print("(10s listen window closed — no further events, normal for idle account)")

        asyncio.run(ws_check())
    except ImportError:
        print("websockets package not installed — run: pip install websockets")

    print("\nDONE — read-only verification complete. No write calls were made.")


if __name__ == "__main__":
    main()
