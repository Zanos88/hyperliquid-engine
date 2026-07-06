import pytest

from risk.sizing import DEFAULT_BTC_SZ_DECIMALS, size, truncate_to_step


def test_size_basic():
    qty = size(equity=100_000, entry_price=60_000, stop_price=59_000, risk_pct=0.0075)
    # (100000 * 0.0075) / 1000 = 0.75, truncated to 5dp
    assert qty == pytest.approx(0.75, abs=1e-5)


def test_size_truncates_down_not_up():
    qty = size(equity=100_000, entry_price=60_000, stop_price=59_997, risk_pct=0.0075)
    raw = (100_000 * 0.0075) / 3
    assert qty <= raw
    assert qty == truncate_to_step(raw, DEFAULT_BTC_SZ_DECIMALS)


def test_size_rejects_zero_risk_distance():
    with pytest.raises(ValueError):
        size(equity=100_000, entry_price=60_000, stop_price=60_000)


def test_size_rejects_out_of_band_risk_pct():
    with pytest.raises(ValueError):
        size(equity=100_000, entry_price=60_000, stop_price=59_000, risk_pct=0.02)


def test_size_rejects_nonpositive_equity():
    with pytest.raises(ValueError):
        size(equity=0, entry_price=60_000, stop_price=59_000)


def test_truncate_to_step():
    assert truncate_to_step(0.123456, 5) == pytest.approx(0.12345)
    assert truncate_to_step(1.0, 0) == 1.0
