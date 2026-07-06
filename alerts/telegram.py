"""Telegram delivery for a NEW, dedicated bot instance.

Hard constraint (build spec section 8): this bot instance, its token, and
its channel are entirely separate from the existing Bullphoric
(ALON/TROLL/ANSEM) production bot. Env vars below are namespaced
BTC_SIGNAL_BOT_* to avoid any accidental collision with Bullphoric's
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID if this ever runs on the same host.
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
        url = f"{TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage"
        try:
            resp = requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=timeout)
            resp.raise_for_status()
            return True
        except requests.RequestException:
            logger.warning("Telegram send failed for chat_id=%s", self.chat_id, exc_info=True)
            return False
