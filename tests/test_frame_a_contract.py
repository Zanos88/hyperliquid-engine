"""Frame A producer↔consumer contract: the entry-signal keyboard emitted by
``main.frame_a_markup`` MUST parse cleanly with the exact split logic the
control-plane handlers use (``telegram_control.handlers.cb_take_signal`` /
``cb_skip_signal``).

The existing control-plane tests exercise the handlers with *hand-written*
callback strings (``"take_0.75_SIG1"``), and nothing exercises the producer,
so a change to the callback_data format in ``frame_a_markup`` could silently
break every live Take/Skip button while every unit test still passes. These
tests close that gap by generating the markup and parsing it the way the
handlers do.

The whole scheme hinges on one invariant: a signal id is a ULID, and ULIDs
(Crockford base32, 0-9A-Z) contain no ``_``. That is what lets the handlers
recover the id with a bounded ``split("_", N)``. The invariant is pinned
explicitly below so a future id-format change can't quietly violate it.
"""
from __future__ import annotations

from ulid import ULID

from main import frame_a_markup


def _buttons(signal_id: str) -> dict[str, str]:
    """{button text: callback_data} for a frame_a_markup signal frame."""
    row = frame_a_markup(signal_id)["inline_keyboard"][0]
    return {b["text"]: b["callback_data"] for b in row}


def test_ulid_signal_id_has_no_underscore():
    # The handler parsers rely on this: take_<pct>_<id> and skip_<id> are only
    # unambiguously splittable because <id> never contains '_'.
    for _ in range(50):
        assert "_" not in str(ULID())


def test_frame_a_markup_shape_and_texts():
    buttons = _buttons(str(ULID()))
    assert set(buttons) == {"Take @ 0.75% risk", "Take @ 0.5%", "Skip"}


def test_take_buttons_round_trip_through_handler_parse():
    signal_id = str(ULID())
    buttons = _buttons(signal_id)

    # Mirror telegram_control.handlers.cb_take_signal exactly:
    #   _, pct_str, signal_id = data.split("_", 2); risk_pct = float(pct_str) / 100
    for data, expected_pct in ((buttons["Take @ 0.75% risk"], 0.75),
                               (buttons["Take @ 0.5%"], 0.5)):
        verb, pct_str, parsed_id = data.split("_", 2)
        assert verb == "take"
        assert float(pct_str) / 100 == expected_pct / 100
        assert parsed_id == signal_id


def test_skip_button_round_trips_through_handler_parse():
    signal_id = str(ULID())
    data = _buttons(signal_id)["Skip"]

    # Mirror telegram_control.handlers.cb_skip_signal exactly:
    #   _, signal_id = data.split("_", 1)
    verb, parsed_id = data.split("_", 1)
    assert verb == "skip"
    assert parsed_id == signal_id
