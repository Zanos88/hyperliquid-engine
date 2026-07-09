"""Track 3 acceptance tests — Part 1: 1D bias access (no-lookahead).

daily_bias_at's own responsibility is the no-lookahead slice + delegation
to compute_bias; compute_bias's directional correctness is bias_4h's
concern (and is exercised on real daily candles by the Part 3 sweep).
So these tests pin the slice boundary and delegation deterministically
(a spy), plus one real thin-history NEUTRAL touch."""
from __future__ import annotations

import strategy.fisher_cycle as fc
from data.feed import Candle
from strategy.bias_4h import Bias, BiasResult
from strategy.fisher_cycle import daily_bias_at

DAY = 86_400_000


def daily(i, close):
    return Candle(open_time_ms=i * DAY, close_time_ms=(i + 1) * DAY,
                  open=close, high=close + 50, low=close - 50, close=close, volume=100.0)


def test_slices_no_lookahead_and_delegates(monkeypatch):
    candles = [daily(i, 60_000 + i) for i in range(20)]   # close_time_ms = (i+1)*DAY
    seen = {}

    def spy(cs, fractal_width=2, sr_lookback=20):
        seen["n"] = len(cs)
        seen["last_close_ms"] = cs[-1].close_time_ms if cs else None
        seen["fw"], seen["srl"] = fractal_width, sr_lookback
        return BiasResult(Bias.BULLISH, None, {}, [], "spy")

    monkeypatch.setattr(fc, "compute_bias", spy)

    # as of the close of candle index 9 (close_time_ms = 10*DAY): 10 visible
    out = daily_bias_at(candles, 10 * DAY)
    assert out == Bias.BULLISH                      # delegation: returns .bias
    assert seen["n"] == 10                          # only candles closed <= ts
    assert seen["last_close_ms"] == 10 * DAY        # boundary candle included
    assert seen["fw"] == 2 and seen["srl"] == 20    # defaults forwarded


def test_custom_params_forwarded(monkeypatch):
    captured = {}

    def spy(cs, fractal_width=2, sr_lookback=20):
        captured["fw"], captured["srl"] = fractal_width, sr_lookback
        return BiasResult(Bias.NEUTRAL, None, {}, [], "spy")

    monkeypatch.setattr(fc, "compute_bias", spy)
    daily_bias_at([daily(0, 1.0)], DAY, fractal_width=3, sr_lookback=40)
    assert captured == {"fw": 3, "srl": 40}


def test_thin_history_is_neutral_real():
    # real compute_bias, too few candles for a confirmed swing -> NEUTRAL
    assert daily_bias_at([daily(i, 60_000) for i in range(3)], 100 * DAY) == Bias.NEUTRAL


# ── Part 2: state-machine decision helpers ──

from strategy.fisher_cycle import (  # noqa: E402
    is_exhausted,
    leg_stop,
    macro_broken,
    opening_direction,
)


def test_opening_direction_pullback_entries():
    # bullish bias + Fisher oversold -> buy the dip (LONG); mirror bearish
    assert opening_direction(Bias.BULLISH, -2.5, 2.0) == "LONG"
    assert opening_direction(Bias.BEARISH, 2.5, 2.0) == "SHORT"
    # not extended enough -> no entry
    assert opening_direction(Bias.BULLISH, -1.9, 2.0) is None
    assert opening_direction(Bias.BEARISH, 1.9, 2.0) is None
    # a short is NEVER opened fresh in a bullish bias (only via flip)
    assert opening_direction(Bias.BULLISH, 2.5, 2.0) is None
    assert opening_direction(Bias.BEARISH, -2.5, 2.0) is None
    assert opening_direction(Bias.NEUTRAL, -2.5, 2.0) is None


def test_is_exhausted_flip_condition():
    # long banks at Fisher +2 (favorable exhaustion); short at -2
    assert is_exhausted("LONG", 2.0, 2.0) is True
    assert is_exhausted("LONG", 1.99, 2.0) is False
    assert is_exhausted("SHORT", -2.0, 2.0) is True
    assert is_exhausted("SHORT", -1.99, 2.0) is False
    # a long is not exhausted by an oversold reading (that's its entry zone)
    assert is_exhausted("LONG", -3.0, 2.0) is False


def test_macro_broken():
    assert macro_broken(Bias.BULLISH, Bias.BEARISH) is True
    assert macro_broken(Bias.BULLISH, Bias.NEUTRAL) is True     # flip to neutral flattens
    assert macro_broken(Bias.BULLISH, Bias.BULLISH) is False


def test_leg_stop_atr_offset_both_directions():
    assert leg_stop("LONG", 100.0, 2.0, atr_mult=1.5) == 97.0   # entry - mult*ATR
    assert leg_stop("SHORT", 100.0, 2.0, atr_mult=1.5) == 103.0  # entry + mult*ATR
    assert leg_stop("LONG", 100.0, 2.0, atr_mult=1.0) == 98.0
