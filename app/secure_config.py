"""
Load configuration from the encrypted secrets file,
falling back to plain environment variables.
"""
import logging
import os

from app.crypto import decrypt_secrets, secrets_file_exists

logger = logging.getLogger(__name__)

# Keys the client must supply (sensitive)
REQUIRED_KEYS = [
    "CREATORS_API_CREDENTIAL_ID",
    "CREATORS_API_CREDENTIAL_SECRET",
    "CREATORS_API_VERSION",
    "PAAPI_PARTNER_TAG",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]

# Optional keys with their defaults
OPTIONAL_KEYS = {
    "CHECK_INTERVAL_SECONDS": "360",
    "CATALOG_REFRESH_HOURS": "8",
    "MAX_PRICE_USD": "180",
    "DB_PATH": "bot.db",
}


def load_into_env() -> None:
    """
    If an encrypted secrets file exists and MASTER_PASSWORD is set,
    decrypt and inject the values into os.environ so the rest of
    the app can keep using os.environ / os.getenv as before.
    """
    master = os.getenv("MASTER_PASSWORD")
    if not secrets_file_exists():
        logger.info("No encrypted secrets file found — using plain env vars")
        return
    if not master:
        logger.info("secrets.enc exists but MASTER_PASSWORD not set — using plain env vars")
        return

    try:
        secrets = decrypt_secrets(master)
    except ValueError as exc:
        logger.error("Failed to decrypt secrets: %s", exc)
        raise RuntimeError("Cannot start: wrong master password") from exc

    injected = 0
    for key, value in secrets.items():
        if key not in os.environ:          # env vars take precedence
            os.environ[key] = str(value)
            injected += 1
    logger.info("Injected %d secrets from encrypted store", injected)
