"""Telegram control plane (V2 build report section 4).

Strictly a CLIENT of the risk + execution services — contains no trading
logic. The Golden Rule (adopted verbatim from the report): slash commands
are global navigation/state; inline buttons are contextual execution with
action+asset embedded in callback_data. Every handler is auth-gated by
the BTC_SIGNAL_BOT_ADMIN_IDS allowlist, and every execution path routes
through the risk gate — no fixed-notional buttons exist.
"""
