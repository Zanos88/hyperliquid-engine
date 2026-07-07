"""Owner + allowlist authorization for every control-plane interaction.

FAIL CLOSED: with BTC_SIGNAL_BOT_ADMIN_IDS unset or empty, nobody is
authorized — the control plane refuses all commands rather than allowing
anyone. Unauthorized attempts are logged (user id + command) and ignored.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def allowed_user_ids() -> frozenset[int]:
    raw = os.environ.get("BTC_SIGNAL_BOT_ADMIN_IDS", "")
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                logger.warning("ignoring malformed admin id %r in BTC_SIGNAL_BOT_ADMIN_IDS", part)
    if not ids:
        logger.error("BTC_SIGNAL_BOT_ADMIN_IDS empty — control plane is LOCKED (fail closed)")
    return frozenset(ids)


def is_authorized(user_id: int | None) -> bool:
    return user_id is not None and user_id in allowed_user_ids()
