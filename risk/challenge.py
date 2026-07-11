"""Challenge-tier floor math — parameterized for static AND trailing tiers.

Single source of truth for the account-level safety thresholds
(docs/GOLD_2STEP_REPARAMETERIZATION.md). Every enforcement/display consumer
(floor-guard trigger mirrors this in SQL, guardian, pre-trade gate, sizing
attenuation, telemetry distances, dashboards) derives its floors from ONE
`ChallengeConfig` + the persisted high-water mark, so a tier change is a
config-row update, not a code hunt.

DEFAULT_CONFIG is the CURRENT live posture (Gold 1-Step-style static 6% @
$94,000, daily 3% of initial) — deploy-neutral by construction: shipping
this code with the default seed changes no behavior. Flipping to the Gold
2-Step tier (trailing 8%, daily 5%) is an explicit, user-gated
`challenge_config` update (Step 4 of the reparameterization spec).

The daily limit is a fixed dollar amount (`daily_loss_pct` of INITIAL
balance), matching the verified live semantics of the current tier
(day_start − $3,000). The drawdown floor's base is the persisted HWM for
trailing tiers and the initial balance for static tiers.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChallengeConfig:
    drawdown_type: str        # "static" | "trailing"
    max_drawdown_pct: float   # e.g. 6.0 (1-Step) / 8.0 (2-Step)
    daily_loss_pct: float     # e.g. 3.0 / 5.0 — % of initial_balance, as $
    initial_balance: float    # e.g. 100_000.0

    def __post_init__(self) -> None:
        if self.drawdown_type not in ("static", "trailing"):
            raise ValueError(f"unknown drawdown_type {self.drawdown_type!r}")
        if not (0 < self.max_drawdown_pct <= 20 and 0 < self.daily_loss_pct <= 10):
            raise ValueError("drawdown/daily percentages outside sane bounds")
        if self.initial_balance <= 0:
            raise ValueError("initial_balance must be positive")


# Current live posture — static seed reproduces the historical hardcodes
# (floor $94,000; daily day_start − $3,000) exactly.
DEFAULT_CONFIG = ChallengeConfig("static", 6.0, 3.0, 100_000.0)


def dd_floor(cfg: ChallengeConfig, hwm: float | None = None) -> float:
    """Max-drawdown floor. Trailing tiers ratchet off the high-water mark
    (never below the initial balance — HWM is monotonically >= initial by
    construction); static tiers anchor to the initial balance."""
    base = cfg.initial_balance
    if cfg.drawdown_type == "trailing" and hwm is not None:
        base = max(hwm, cfg.initial_balance)
    return base * (1.0 - cfg.max_drawdown_pct / 100.0)


def daily_floor(cfg: ChallengeConfig, day_start_equity: float) -> float:
    return day_start_equity - cfg.initial_balance * cfg.daily_loss_pct / 100.0


def binding_floor(cfg: ChallengeConfig, day_start_equity: float,
                  hwm: float | None = None) -> float:
    return max(daily_floor(cfg, day_start_equity), dd_floor(cfg, hwm))
