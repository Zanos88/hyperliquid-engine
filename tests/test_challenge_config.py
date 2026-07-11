"""Acceptance tests for the challenge-tier parameterization (Gold 2-Step reparam).

Pure-math layer only; DB-level behavior (config row, HWM upsert, rewritten
floor-guard trigger) is exercised by scripts/stress_trailing_floor.py against
the staging project.
"""
from __future__ import annotations

import pytest

from risk.challenge import (
    DEFAULT_CONFIG,
    ChallengeConfig,
    binding_floor,
    daily_floor,
    dd_floor,
)
from risk.gate import binding_floor as gate_binding_floor

GOLD_2STEP = ChallengeConfig("trailing", 8.0, 5.0, 100_000.0)


def test_static_seed_reproduces_historical_floors():
    # The deploy-neutral guarantee: defaults == the old hardcodes, exactly.
    assert dd_floor(DEFAULT_CONFIG) == 94_000.0
    assert daily_floor(DEFAULT_CONFIG, 100_000) == 97_000.0
    assert binding_floor(DEFAULT_CONFIG, 100_000) == 97_000.0          # daily binds
    assert binding_floor(DEFAULT_CONFIG, 96_000) == 94_000.0           # static binds
    # And the gate wrapper's default path is identical to the old formula.
    assert gate_binding_floor(100_000) == max(100_000 - 3_000, 94_000)
    assert gate_binding_floor(96_000) == max(96_000 - 3_000, 94_000)


def test_trailing_floor_ratchets_with_hwm():
    assert dd_floor(GOLD_2STEP, hwm=100_000) == 92_000.0
    assert dd_floor(GOLD_2STEP, hwm=110_000) == pytest.approx(101_200.0)
    # HWM below initial can never lower the floor (monotonic-from-initial).
    assert dd_floor(GOLD_2STEP, hwm=95_000) == 92_000.0
    # Missing HWM degrades to the initial-balance base, never explodes.
    assert dd_floor(GOLD_2STEP, hwm=None) == 92_000.0


def test_trailing_crosses_above_old_static_at_documented_hwm():
    # docs/FEEDBACK_DD_FREQUENCY_REVIEW.md §2: trailing floor exceeds the old
    # 94,000 static assumption once HWM > 94,000/0.92 = 102,173.9...
    crossover = 94_000 / 0.92
    assert dd_floor(GOLD_2STEP, hwm=crossover - 1) < 94_000
    assert dd_floor(GOLD_2STEP, hwm=crossover + 1) > 94_000


def test_gold_2step_daily_floor_is_5pct_of_initial():
    assert daily_floor(GOLD_2STEP, 100_000) == 95_000.0
    assert daily_floor(GOLD_2STEP, 103_000) == 98_000.0


def test_binding_floor_takes_the_higher_constraint():
    # Late-challenge trailing case: HWM 110k -> dd floor 101,200 dominates
    # the daily floor (day_start 104k -> 99k).
    assert binding_floor(GOLD_2STEP, 104_000, hwm=110_000) == pytest.approx(101_200.0)
    # Early case: daily binds (100k day start -> 95k vs dd 92k).
    assert binding_floor(GOLD_2STEP, 100_000, hwm=100_000) == 95_000.0


def test_config_validation_fails_loudly():
    with pytest.raises(ValueError):
        ChallengeConfig("weird", 8.0, 5.0, 100_000.0)
    with pytest.raises(ValueError):
        ChallengeConfig("static", 0.0, 5.0, 100_000.0)
    with pytest.raises(ValueError):
        ChallengeConfig("static", 6.0, 5.0, -1.0)
