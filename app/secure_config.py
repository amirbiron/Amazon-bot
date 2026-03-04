"""
Load configuration from two sources:
1. Environment variables — set by the DEVELOPER in Render dashboard
2. Encrypted client secrets file — set by the CLIENT via the web panel

Client secrets take lower priority: env vars always win.
"""
import logging
import os

from app.crypto import load_client_secrets, client_secrets_exist

logger = logging.getLogger(__name__)

# ── Keys the DEVELOPER sets in Render env vars ────────────────────────────────
DEVELOPER_KEYS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]

# ── Keys the CLIENT enters via the web panel ──────────────────────────────────
CLIENT_KEYS = [
    "CREATORS_API_CREDENTIAL_ID",
    "CREATORS_API_CREDENTIAL_SECRET",
    "CREATORS_API_VERSION",
    "PAAPI_PARTNER_TAG",
]

# All required for the bot to run
ALL_REQUIRED_KEYS = DEVELOPER_KEYS + CLIENT_KEYS

# Optional keys with their defaults
OPTIONAL_KEYS = {
    "CHECK_INTERVAL_SECONDS": "360",
    "CATALOG_REFRESH_HOURS": "8",
    "MAX_PRICE_USD": "180",
    "DB_PATH": "bot.db",
}


def load_client_secrets_into_env() -> None:
    """
    Read the encrypted client secrets file and inject values into
    os.environ so the rest of the app can use os.getenv as before.
    Env vars already set (by the developer) take precedence.
    """
    if not client_secrets_exist():
        logger.info("No client secrets file found — waiting for client to configure via panel")
        return

    secrets = load_client_secrets()
    if not secrets:
        logger.warning("Client secrets file exists but could not be read")
        return

    injected = 0
    for key, value in secrets.items():
        if key not in os.environ:
            os.environ[key] = str(value)
            injected += 1
    logger.info("Injected %d client secrets from encrypted store", injected)


def all_required_present() -> bool:
    """Check if all required keys are available in os.environ."""
    return all(os.getenv(k) for k in ALL_REQUIRED_KEYS)
