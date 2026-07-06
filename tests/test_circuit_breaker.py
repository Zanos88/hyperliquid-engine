from risk.circuit_breaker import HALT_THRESHOLD_PCT, CircuitBreaker


def test_no_halt_within_bounds():
    cb = CircuitBreaker(day_start_equity=100_000)
    cb.update(current_equity=99_000)  # -1%
    assert not cb.is_halted()
    assert not cb.just_tripped()


def test_halts_at_threshold():
    cb = CircuitBreaker(day_start_equity=100_000)
    cb.update(current_equity=100_000 * (1 + HALT_THRESHOLD_PCT))  # exactly -2.5%
    assert cb.is_halted()
    assert cb.just_tripped()


def test_halts_beyond_threshold():
    cb = CircuitBreaker(day_start_equity=100_000)
    cb.update(current_equity=97_000)  # -3%
    assert cb.is_halted()


def test_just_tripped_only_fires_once():
    cb = CircuitBreaker(day_start_equity=100_000)
    cb.update(current_equity=97_000)
    assert cb.just_tripped()
    cb.update(current_equity=96_000)  # still halted, further loss
    assert cb.is_halted()
    assert not cb.just_tripped()  # already tripped, no repeat alert


def test_reset_for_new_day_clears_halt():
    cb = CircuitBreaker(day_start_equity=100_000)
    cb.update(current_equity=97_000)
    assert cb.is_halted()
    cb.reset_for_new_day(new_day_start_equity=97_000)
    assert not cb.is_halted()
    cb.update(current_equity=97_000)
    assert not cb.is_halted()


def test_rejects_nonpositive_day_start_equity():
    cb = CircuitBreaker(day_start_equity=0)
    try:
        cb.update(current_equity=100)
        assert False, "expected ValueError"
    except ValueError:
        pass
