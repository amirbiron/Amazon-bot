import requests
import logging
from datetime import datetime, timedelta
from app import db, config

logger = logging.getLogger(__name__)


def get_valid_token() -> str:
    """
    Returns a valid Bearer token.
    Uses cached token from DB if still valid (with 5-min buffer).
    Fetches a new one when expired.
    """
    cached = db.get_token_cache()
    if cached:
        expires_at = datetime.fromisoformat(cached["expires_at"])
        if datetime.utcnow() < expires_at - timedelta(minutes=5):
            return cached["access_token"]

    logger.info("Fetching new OAuth token...")
    token, expires_in = _fetch_token()
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    db.set_token_cache(token, expires_at.isoformat())
    logger.info("New token cached, expires at %s", expires_at.isoformat())
    return token


def _fetch_token():
    payload = {
        "grant_type": "client_credentials",
        "scope":      "creatorsapi/default",
    }
    # Cognito requires client credentials via HTTP Basic Auth
    auth = (config.CREATORS_CREDENTIAL_ID, config.CREATORS_CREDENTIAL_SECRET)

    # Debug: log what we're sending (mask the secret)
    masked_id = config.CREATORS_CREDENTIAL_ID[:4] + "..." if config.CREATORS_CREDENTIAL_ID else "<empty>"
    masked_secret = config.CREATORS_CREDENTIAL_SECRET[:4] + "..." if config.CREATORS_CREDENTIAL_SECRET else "<empty>"
    logger.info(
        "OAuth request → url=%s  client_id=%s  client_secret=%s  scope=%s",
        config.TOKEN_URL, masked_id, masked_secret, payload["scope"],
    )

    resp = requests.post(config.TOKEN_URL, data=payload, auth=auth, timeout=15)
    if not resp.ok:
        logger.error("OAuth response %s: %s", resp.status_code, resp.text)
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], int(data.get("expires_in", 3600))
