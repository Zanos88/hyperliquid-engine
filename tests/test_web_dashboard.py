"""Web dashboard acceptance tests: fail-closed auth, login/cookie flow,
view-only guarantee. DB layer is mocked — no network."""
from __future__ import annotations

import importlib.util
import os
import pathlib

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

WEB_API = pathlib.Path(__file__).resolve().parent.parent / "web" / "api" / "index.py"

spec = importlib.util.spec_from_file_location("web_dashboard_api", WEB_API)
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

# https base URL so Secure cookies are stored and replayed by the client
client = TestClient(web.app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client.cookies.clear()


def configure(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "k" * 32)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct-horse")


# ── fail closed ──

def test_unconfigured_returns_503_everywhere():
    for path in ("/api/status", "/api/equity", "/api/events"):
        r = client.get(path)
        assert r.status_code == 503
        assert r.json()["error"] == "auth_not_configured"
    r = client.post("/api/login", json={"password": "anything"})
    assert r.status_code == 503


def test_unauthorized_401_when_configured(monkeypatch):
    configure(monkeypatch)
    r = client.get("/api/status")
    assert r.status_code == 401

    r = client.get("/api/status", headers={"x-api-key": "wrong"})
    assert r.status_code == 401

    r = client.post("/api/login", json={"password": "wrong"})
    assert r.status_code == 401


# ── happy paths ──

def test_login_sets_cookie_and_grants_access(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(web, "_query", lambda sql, params=(): [])

    r = client.post("/api/login", json={"password": "correct-horse"})
    assert r.status_code == 200
    assert web.COOKIE_NAME in r.cookies

    r2 = client.get("/api/status")            # cookie carried by TestClient
    assert r2.status_code == 200
    assert r2.json()["static_floor"] == 94000.0


def test_api_key_header_grants_access(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(web, "_query", lambda sql, params=(): [])
    r = client.get("/api/equity", headers={"x-api-key": "k" * 32})
    assert r.status_code == 200
    assert r.json() == {"series": []}


def test_tampered_cookie_rejected(monkeypatch):
    configure(monkeypatch)
    client.cookies.set(web.COOKIE_NAME, "9999999999.deadbeef")
    r = client.get("/api/status")
    assert r.status_code == 401


# ── view-only guarantee ──

def test_web_has_no_execution_paths():
    src = WEB_API.read_text(encoding="utf-8")
    for banned in ("execution", "create_order", "kill_sequence", "close_position",
                   "propr_client", "ProprClient"):
        assert banned not in src, f"web dashboard must not reference {banned}"
    # and it never writes to the DB
    for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert verb not in src, f"web dashboard must be read-only (found {verb})"
