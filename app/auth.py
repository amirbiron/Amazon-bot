import requests
import logging
from datetime import datetime, timedelta
from app import db, config

logger = logging.getLogger(__name__)

# Fallback token endpoints to try when the primary Cognito endpoint fails.
# v3.1 credentials may use a different OAuth provider.
_LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


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


def _mask(value: str) -> str:
    return (value[:4] + "...") if value else "<empty>"


def _try_cognito_basic(url: str, cid: str, secret: str) -> requests.Response:
    """Strategy 1: Cognito with HTTP Basic Auth (works for v2.x credentials)."""
    payload = {"grant_type": "client_credentials", "scope": "creatorsapi/default"}
    return requests.post(url, data=payload, auth=(cid, secret), timeout=15)


def _try_cognito_body(url: str, cid: str, secret: str) -> requests.Response:
    """Strategy 2: Cognito with credentials in POST body (client_secret_post)."""
    payload = {
        "grant_type": "client_credentials",
        "scope": "creatorsapi/default",
        "client_id": cid,
        "client_secret": secret,
    }
    return requests.post(url, data=payload, timeout=15)


def _try_lwa(cid: str, secret: str) -> requests.Response:
    """Strategy 3: Login With Amazon endpoint (may be needed for v3.x credentials)."""
    payload = {
        "grant_type": "client_credentials",
        "client_id": cid,
        "client_secret": secret,
        "scope": "creatorsapi/default",
    }
    return requests.post(_LWA_TOKEN_URL, data=payload, timeout=15)


def _fetch_token():
    cid = config.CREATORS_CREDENTIAL_ID
    secret = config.CREATORS_CREDENTIAL_SECRET
    url = config.TOKEN_URL

    strategies = [
        ("Cognito+BasicAuth", lambda: _try_cognito_basic(url, cid, secret)),
        ("Cognito+BodyParams", lambda: _try_cognito_body(url, cid, secret)),
        ("LWA", lambda: _try_lwa(cid, secret)),
    ]

    logger.info(
        "OAuth request → url=%s  client_id=%s  client_secret=%s",
        url, _mask(cid), _mask(secret),
    )

    last_resp = None
    for name, strategy in strategies:
        resp = strategy()
        if resp.ok:
            data = resp.json()
            logger.info("OAuth succeeded with strategy: %s", name)
            return data["access_token"], int(data.get("expires_in", 3600))
        logger.warning(
            "OAuth strategy %s failed (%s): %s", name, resp.status_code, resp.text
        )
        last_resp = resp

    # All strategies failed — raise the last error
    logger.error("All OAuth strategies exhausted. Last response: %s %s",
                 last_resp.status_code, last_resp.text)
    last_resp.raise_for_status()
