"""Confluence-insight acceptance tests: the summary line names the exact
blocker; health probe shapes; status payload carries readings."""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

from telegram_control.handlers import confluence_line


def r(enabled, vote):
    return {"enabled": enabled, "vote": vote}


def test_all_aligned_long():
    readings = {"bias_sr": r(True, "LONG"), "fisher": r(True, "LONG"), "obv": r(True, "LONG"),
                "rsi": r(False, "NONE"), "ichimoku": r(False, "NONE")}
    assert confluence_line(readings) == "Confluence: ALL 3 aligned LONG"


def test_blocker_named():
    readings = {"bias_sr": r(True, "LONG"), "fisher": r(True, "NONE"), "obv": r(True, "LONG"),
                "rsi": r(False, "NONE"), "ichimoku": r(False, "NONE")}
    line = confluence_line(readings)
    assert line == "Confluence: 2/3 LONG — waiting on: Fisher"


def test_split_votes():
    readings = {"bias_sr": r(True, "LONG"), "fisher": r(True, "SHORT"), "obv": r(True, "SHORT")}
    line = confluence_line(readings)
    assert "2/3 SHORT" in line and "split" in line


def test_none_enabled_and_missing():
    assert confluence_line(None) is None
    assert confluence_line({"bias_sr": r(False, "LONG")}) == "Confluence: no indicators enabled"


# ── web: health probe + readings in status payload ──

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

WEB_API = pathlib.Path(__file__).resolve().parent.parent / "web" / "api" / "index.py"
spec = importlib.util.spec_from_file_location("web_dashboard_api_conf", WEB_API)
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)
client = TestClient(web.app, base_url="https://testserver")


def test_health_no_db_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    resp = client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json() == {"db": "error", "type": "DatabaseUrlNotSet"}


def test_health_ok_and_error_shapes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(web, "_query", lambda sql, params=(): [(1,)])
    assert client.get("/api/health").json() == {"db": "ok"}

    def boom(sql, params=()):
        raise ConnectionError("nope")
    monkeypatch.setattr(web, "_query", boom)
    resp = client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json() == {"db": "error", "type": "ConnectionError"}
    # never leaks values — only a class name
    assert "nope" not in resp.text and "postgresql" not in resp.text


def test_status_includes_readings_and_signals_today(monkeypatch):
    import datetime as dt
    monkeypatch.setenv("DASHBOARD_API_KEY", "k" * 32)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    now = dt.datetime(2026, 7, 8, 5, 0, tzinfo=dt.timezone.utc)
    readings = {"fisher": {"enabled": True, "vote": "NONE", "cross": "none", "value": 0.42}}

    def fake_query(sql, params=()):
        if "FROM market_state" in sql:
            return [(now, 61780.0, "NEUTRAL", "below 0.618", None, None, None, None, readings)]
        if "FROM pending_signals" in sql:
            return [(3,)]
        if "FROM engine_state" in sql:
            return [("PAUSED", now)]
        return []

    monkeypatch.setattr(web, "_query", fake_query)
    resp = client.get("/api/status", headers={"x-api-key": "k" * 32})
    body = resp.json()
    assert body["market"]["readings"]["fisher"]["value"] == 0.42
    assert body["signals_today"] == 3
