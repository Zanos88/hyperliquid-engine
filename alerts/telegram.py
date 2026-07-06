"""Telegram delivery for a NEW, dedicated bot instance.

SCAFFOLD ONLY. Hard constraint (build spec section 8): this bot instance,
its token, and its channel are entirely separate from the existing
Bullphoric (ALON/TROLL/ANSEM) production bot. Env vars below are
namespaced BTC_SIGNAL_BOT_* to avoid any accidental collision with
Bullphoric's TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID if this ever runs on
the same host.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramConfigError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        self.bot_token = bot_token or os.environ.get("BTC_SIGNAL_BOT_TELEGRAM_TOKEN")
        self.chat_id = chat_id or os.environ.get("BTC_SIGNAL_BOT_TELEGRAM_CHAT_ID")
        if not self.bot_token or not self.chat_id:
            raise TelegramConfigError(
                "BTC_SIGNAL_BOT_TELEGRAM_TOKEN and BTC_SIGNAL_BOT_TELEGRAM_CHAT_ID must both be set "
                "— this bot must use its own dedicated token/channel, never Bullphoric's."
            )

    def send(self, text: str, timeout: float = 10.0) -> bool:
        """TODO(Fable): POST to {TELEGRAM_API_BASE}/bot{token}/sendMessage with
        {"chat_id": self.chat_id, "text": text}. On failure, log a WARNING
        (never a silent except: pass — this project's #1 recurring bug class)
        and return False; return True on success.
        """
        raise NotImplementedError
