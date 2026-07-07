"""Phase 2 acceptance tests — V2 report's sizing/gate acceptance criteria:

- at equity=100k/peak=100k -> full risk
- at equity=97k/peak=103k  -> visibly attenuated
- at floor(+buffer)        -> zero / gate-rejected
plus edge cases (no div-by-zero, no complex numbers) and every gate check.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from risk.gate import GateDecision, binding_floor, evaluate_gate
from risk.sizing import MIN_RISK_PCT, attenuation, size_attenuated
from strategy.signals import Signal, SignalDirection


def make_signal(entry=60_000.0, stop=59_000.0, target=62_500.0):
    return Signal(
        direction=SignalDirection.LONG, entry=entry, stop=stop, target=target,
        reward_risk=abs(target - entry) / abs(entry - stop),
        timestamp=datetime.now(timezone.utc), bias_reason="t", trigger_reason="t",
    )


# ── attenuation acceptance cases (report section 8) ──

def test_full_risk_at_peak():
    assert attenuation(100_000, 100_000) == pytest.approx(1.0)
    qty, risk_usd, att = size_attenuated(100_000, 100_000, 60_000, 59_000, risk_pct=0.0075)
    assert att == pytest.approx(1.0)
    assert risk_usd == pytest.approx(750.0)          # full 0.75%
    assert qty == pytest.approx(0.75, abs=1e-5)


def test_visibly_attenuated_in_drawdown():
    # equity=97k, peak=103k: base=(3000/9000)=1/3 -> (1/3)^1.5 ~= 0.1925
    att = attenuation(97_000, 103_000)
    assert att == pytest.approx((1 / 3) ** 1.5, rel=1e-9)
    assert att < 0.2                                  # visibly attenuated
    _, risk_usd, _ = size_attenuated(97_000, 103_000, 60_000, 59_000, risk_pct=0.0075)
    assert risk_usd == pytest.approx(97_000 * 0.0075 * att)
    assert risk_usd < 150                             # vs $727.5 unattenuated


def test_zero_at_floor():
    assert attenuation(94_000, 100_000) == 0.0
    assert attenuation(93_500, 100_000) == 0.0        # below floor -> 0, not complex


def test_degenerate_peak_fails_safe():
    assert attenuation(95_000, 94_000) == 0.0         # peak at floor -> 0, no div-by-zero
    assert attenuation(95_000, 93_000) == 0.0         # peak below floor -> 0


def test_stale_peak_clamps_to_one():
    assert attenuation(101_000, 100_000) == pytest.approx(1.0)


def test_alpha_below_one_rejected():
    with pytest.raises(ValueError):
        attenuation(100_000, 100_000, alpha=0.5)


def test_widened_risk_floor_quarter_percent():
    assert MIN_RISK_PCT == 0.0025
    qty, risk_usd, _ = size_attenuated(100_000, 100_000, 60_000, 59_000, risk_pct=0.0025)
    assert risk_usd == pytest.approx(250.0)
    with pytest.raises(ValueError):
        size_attenuated(100_000, 100_000, 60_000, 59_000, risk_pct=0.002)   # below 0.25%
    with pytest.raises(ValueError):
        size_attenuated(100_000, 100_000, 60_000, 59_000, risk_pct=0.011)   # above 1.0%


# ── binding floor ──

def test_binding_floor_daily_binds_when_higher():
    assert binding_floor(100_000) == 97_000            # 100k - 3k > 94k
    assert binding_floor(96_000) == 94_000             # 96k - 3k < 94k -> static floor binds


# ── gate checks ──

BASE = dict(equity=100_000, peak_equity=100_000, day_start_equity=100_000,
            open_positions_count=0)


def test_gate_approves_happy_path():
    d = evaluate_gate("ACTIVE", make_signal(), **BASE)
    assert d.approved, d.reasons
    assert d.quantity == pytest.approx(0.75, abs=1e-5)
    assert d.binding_floor == 97_000
    assert d.worst_case_equity == pytest.approx(100_000 - 750, abs=1)


def test_gate_rejects_non_active_states():
    for state in ("PAUSED", "KILLED"):
        d = evaluate_gate(state, make_signal(), **BASE)
        assert not d.approved
        assert any("not ACTIVE" in r for r in d.reasons)


def test_gate_rejects_low_rr():
    sig = make_signal(entry=60_000, stop=59_000, target=61_500)   # R:R 1.5
    d = evaluate_gate("ACTIVE", sig, **BASE)
    assert not d.approved
    assert any("R:R" in r for r in d.reasons)


def test_gate_rejects_max_concurrent():
    d = evaluate_gate("ACTIVE", make_signal(), **{**BASE, "open_positions_count": 1})
    assert not d.approved
    assert any("max concurrent" in r for r in d.reasons)


def test_gate_rejects_worst_case_floor_breach():
    # Day-start 100k -> daily floor 97k (+500 buffer = 97.5k). At equity
    # 97.7k the attenuated risk (~$355) still lands worst-case ~97,345,
    # below the 97,500 line -> reject. (At 97.9k attenuation alone already
    # clears the buffer -- that self-protection is by design and covered
    # by test_attenuation_self_protects_near_buffer below.)
    d = evaluate_gate(
        "ACTIVE", make_signal(),
        equity=97_700, peak_equity=100_000, day_start_equity=100_000,
        open_positions_count=0,
    )
    assert not d.approved
    assert any("worst-case" in r for r in d.reasons)


def test_attenuation_self_protects_near_buffer():
    # Same setup slightly higher: attenuation shrinks risk enough that the
    # worst case clears floor+buffer -- approved, with visibly reduced size.
    d = evaluate_gate(
        "ACTIVE", make_signal(),
        equity=97_900, peak_equity=100_000, day_start_equity=100_000,
        open_positions_count=0,
    )
    assert d.approved, d.reasons
    assert d.attenuation_applied < 0.6           # far below full risk
    assert d.worst_case_equity > d.binding_floor + 500


def test_gate_rejects_dust_quantity_near_floor():
    # Deep attenuation truncates quantity below the 0.001 BTC venue minimum.
    d = evaluate_gate(
        "ACTIVE", make_signal(),
        equity=94_150, peak_equity=103_000, day_start_equity=94_150,
        open_positions_count=0,
    )
    assert not d.approved
    assert any("venue minimum" in r or "worst-case" in r for r in d.reasons)


def test_gate_names_every_failure():
    sig = make_signal(entry=60_000, stop=59_000, target=61_000)   # R:R 1.0
    d = evaluate_gate("KILLED", sig, **{**BASE, "open_positions_count": 3})
    assert not d.approved
    assert len(d.reasons) >= 3    # state + R:R + concurrency all named
