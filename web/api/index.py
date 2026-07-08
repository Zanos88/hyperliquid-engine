"""btc-signal-bot web dashboard API — Vercel serverless (FastAPI/ASGI).

VIEW-ONLY by design: read-only Supabase queries, zero imports from the
bot's trading modules, no order paths of any kind. Actions stay in the
Telegram control plane. (tests/test_web_dashboard.py mechanically
enforces both properties against this file's source.)

Auth (mirrors the established fail-closed pattern):
- DASHBOARD_API_KEY or DASHBOARD_PASSWORD unset  -> every endpoint 503
  ("auth_not_configured") — fail closed, never open.
- Browser flow: POST /api/login {password} vs DASHBOARD_PASSWORD
  (hmac.compare_digest) -> HttpOnly cookie carrying an HMAC-signed
  expiring token (secret = DASHBOARD_API_KEY).
- Server-to-server: x-api-key header vs DASHBOARD_API_KEY.

Data: psycopg -> Supabase SESSION POOLER via DATABASE_URL (IPv4-safe
from Vercel). No fabricated fields: anything unavailable returns null.
"""
from __future__ import annotations

import hmac
import os
import time
from hashlib import sha256

from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()

_DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    """Serve the dashboard shell (the login form IS the gate — all data
    endpoints stay behind auth; the shell contains no data)."""
    try:
        return HTMLResponse(_DASHBOARD_HTML.read_text(encoding="utf-8"))
    except OSError:
        return HTMLResponse("<h1>dashboard asset missing</h1>", status_code=500)

COOKIE_NAME = "btcbot_session"
SESSION_TTL_SECONDS = 12 * 3600


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _sign(expiry: int) -> str:
    return hmac.new(_env("DASHBOARD_API_KEY").encode(), str(expiry).encode(), sha256).hexdigest()


def _make_token() -> str:
    expiry = int(time.time()) + SESSION_TTL_SECONDS
    return f"{expiry}.{_sign(expiry)}"


def _token_valid(token: str) -> bool:
    try:
        expiry_s, sig = token.split(".", 1)
        expiry = int(expiry_s)
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(_sign(expiry), sig) and expiry > time.time()


def _auth(request: Request) -> JSONResponse | None:
    """Fail-closed guard: 503 unconfigured, 401 unauthorized, None if OK."""
    if not _env("DASHBOARD_API_KEY") or not _env("DASHBOARD_PASSWORD"):
        return JSONResponse(
            {"error": "auth_not_configured",
             "detail": "DASHBOARD_API_KEY / DASHBOARD_PASSWORD not set — refusing to serve data"},
            status_code=503)
    provided_key = request.headers.get("x-api-key", "")
    if provided_key and hmac.compare_digest(provided_key, _env("DASHBOARD_API_KEY")):
        return None
    cookie = request.cookies.get(COOKIE_NAME, "")
    if cookie and _token_valid(cookie):
        return None
    return JSONResponse({"error": "unauthorized"}, status_code=401)


def _query(sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(_env("DATABASE_URL"), autocommit=True, connect_timeout=8) as conn:
        return conn.execute(sql, params).fetchall()


@app.post("/api/login")
async def login(request: Request) -> JSONResponse:
    if not _env("DASHBOARD_API_KEY") or not _env("DASHBOARD_PASSWORD"):
        return JSONResponse({"error": "auth_not_configured"}, status_code=503)
    body = await request.json()
    password = str(body.get("password", ""))
    if not hmac.compare_digest(password, _env("DASHBOARD_PASSWORD")):
        return JSONResponse({"error": "invalid_password"}, status_code=401)
    resp = JSONResponse({"status": "ok"})
    resp.set_cookie(COOKIE_NAME, _make_token(), max_age=SESSION_TTL_SECONDS,
                    httponly=True, secure=True, samesite="lax", path="/")
    return resp


@app.get("/api/status")
async def status(request: Request) -> JSONResponse:
    denied = _auth(request)
    if denied is not None:
        return denied
    try:
        tel = _query("""SELECT ts, equity, day_start_equity, engine_state,
                               open_positions, open_risk_usd, cb_halted
                        FROM portfolio_telemetry ORDER BY ts DESC, id DESC LIMIT 1""")
        ms = _query("""SELECT ts, last_price, bias, bias_reason, long_stop, long_target,
                              short_stop, short_target FROM market_state WHERE id = 1""")
        st = _query("SELECT state, updated_at FROM engine_state WHERE id = 1")
        ss = _query("""SELECT mode, prod_bias_tf, prod_trigger_tf, test_bias_tf, test_trigger_tf
                       FROM strategy_settings WHERE id = 1""")
    except Exception:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)

    out: dict = {"static_floor": 94_000.0, "daily_loss_limit": 3_000.0}
    if tel:
        ts, equity, day_start, eng, open_n, open_risk, cb = tel[0]
        equity, day_start = float(equity), float(day_start)
        out["telemetry"] = {
            "ts": ts.isoformat(), "equity": equity, "day_start_equity": day_start,
            "daily_pnl": equity - day_start,
            "daily_buffer_left": max(equity - (day_start - 3_000), 0.0),
            "dd_buffer_left": max(equity - 94_000, 0.0),
            "open_positions": open_n,
            "open_risk_usd": float(open_risk) if open_risk is not None else None,
            "cb_halted": cb,
        }
    if ms:
        ts, last_price, bias, reason, ls, lt, ss_, st_ = ms[0]
        out["market"] = {
            "ts": ts.isoformat(), "last_price": float(last_price), "bias": bias,
            "bias_reason": reason,
            "long_stop": float(ls) if ls is not None else None,
            "long_target": float(lt) if lt is not None else None,
            "short_stop": float(ss_) if ss_ is not None else None,
            "short_target": float(st_) if st_ is not None else None,
        }
    if st:
        out["engine_state"] = st[0][0]
    if ss:
        mode, pb, pt, tb, tt = ss[0]
        out["settings"] = {"mode": mode,
                           "active_bias_tf": pb if mode == "production" else tb,
                           "active_trigger_tf": pt if mode == "production" else tt}
    return JSONResponse(out)


@app.get("/api/equity")
async def equity_series(request: Request) -> JSONResponse:
    denied = _auth(request)
    if denied is not None:
        return denied
    try:
        rows = _query("""SELECT ts, equity FROM portfolio_telemetry
                         ORDER BY ts DESC, id DESC LIMIT 288""")
    except Exception:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    series = [{"ts": r[0].isoformat(), "equity": float(r[1])} for r in reversed(rows)]
    return JSONResponse({"series": series})


@app.get("/api/events")
async def events(request: Request) -> JSONResponse:
    denied = _auth(request)
    if denied is not None:
        return denied
    try:
        risk = _query("""SELECT ts, event_type, detail FROM risk_events
                         ORDER BY ts DESC LIMIT 20""")
        sigs = _query("""SELECT created_at, direction, entry, stop, target, reward_risk, status
                         FROM pending_signals ORDER BY created_at DESC LIMIT 10""")
    except Exception:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    return JSONResponse({
        "risk_events": [{"ts": r[0].isoformat(), "type": r[1], "detail": r[2]} for r in risk],
        "signals": [{"ts": s[0].isoformat(), "direction": s[1], "entry": float(s[2]),
                     "stop": float(s[3]), "target": float(s[4]),
                     "reward_risk": float(s[5]), "status": s[6]} for s in sigs],
    })
