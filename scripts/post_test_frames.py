"""UI smoke utility: post one Frame A and one Frame B TEST message to the
real channel to verify inline buttons render and callbacks round-trip.

Dry-run-safe: the pending signal is clearly labeled TEST; any Take tap
routes through the real gate and dry-run execution service (nothing
dispatches); Frame B taps reply "No open BTC position" pre-purchase.

Run:  railway run --service btc-signal-bot python scripts/post_test_frames.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ulid import ULID

from alerts.telegram import TelegramClient
from db.store import TelemetryStore
from main import frame_a_markup
from telegram_control.handlers import frame_b_markup


def main() -> None:
    store = TelemetryStore()
    store.apply_schema()
    telegram = TelegramClient()

    # Frame A — synthetic signal, plausible numbers, clearly labeled TEST
    signal_id = str(ULID())
    entry, stop, target = 61_780.0, 60_900.0, 63_600.0
    rr = (target - entry) / (entry - stop)
    store.create_pending_signal(signal_id, "LONG", entry, stop, target, rr)

    frame_a_text = (
        "\U0001F9EA TEST FRAME A — UI verification only, NOT a real signal\n"
        "\U0001F3AF BTC-PERP LONG SIGNAL (synthetic)\n"
        f"Entry: ${entry:,.2f} | Stop: ${stop:,.2f} | Target: ${target:,.2f} (R:R {rr:.1f})\n"
        "Tap a button to verify the callback round-trip (dry-run, nothing executes)."
    )
    ok_a = telegram.send(frame_a_text, reply_markup=frame_a_markup(signal_id))
    print(f"Frame A posted: sent={ok_a} signal_id={signal_id}")

    # Frame B — dashboard-style sample with the position buttons
    frame_b_text = (
        "\U0001F9EA TEST FRAME B — UI verification only\n"
        "\U0001F4CB POSITION DASHBOARD (sample)\n"
        "LONG 0.75000 BTC @ $61,780 | mark $61,900 | uPnL +$90\n"
        "Buttons below should render; taps will answer 'No open BTC position' in dry-run."
    )
    ok_b = telegram.send(frame_b_text, reply_markup=frame_b_markup("BTC"))
    print(f"Frame B posted: sent={ok_b}")

    if not (ok_a and ok_b):
        sys.exit("one or both frames failed to send — check WARNING logs above")


if __name__ == "__main__":
    main()
