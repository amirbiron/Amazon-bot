import requests
import logging
from datetime import datetime, timedelta
from app import db, config

logger = logging.getLogger(__name__)

_LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"

# Possible scopes to try on the LWA endpoint for v3.x credentials.
# Amazon hasn't publicly documented the Creators API scope for LWA yet,
# so we try several common patterns.
_LWA_SCOPES = [
    "creatorsapi::default",
    "creatorsapi:default",
    "profile",
    "",  # no scope at all
]


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


def _post_safe(url: str, **kwargs) -> requests.Response | None:
    """POST with network-error resilience so the fallback loop continues."""
    try:
        return requests.post(url, timeout=15, **kwargs)
    except requests.RequestException as exc:
        logger.warning("Network error reaching %s: %s", url, exc)
        return None


def _build_strategies(url: str, cid: str, secret: str, version: str):
    """
    Build an ordered list of (name, callable) auth strategies.
    v2.x → only Cognito.  v3.x → only LWA (with scope probing).
    """
    strategies = []
    if version.startswith("2."):
        # Cognito with HTTP Basic Auth (proven for v2.x)
        strategies.append(("Cognito+BasicAuth", lambda: _post_safe(
            url,
            data={"grant_type": "client_credentials", "scope": "creatorsapi/default"},
            auth=(cid, secret),
        )))
    else:
        # v3.x credentials → LWA endpoint, try multiple scopes
        for scope in _LWA_SCOPES:
            payload = {
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": secret,
            }
            if scope:
                payload["scope"] = scope
            label = f"LWA(scope={scope or '<none>'})"
            # capture payload by value
            strategies.append((label, lambda p=dict(payload): _post_safe(
                _LWA_TOKEN_URL, data=p,
            )))
    return strategies


def _fetch_token():
    cid = config.CREATORS_CREDENTIAL_ID
    secret = config.CREATORS_CREDENTIAL_SECRET
    url = config.TOKEN_URL
    version = config.CREATORS_VERSION

    strategies = _build_strategies(url, cid, secret, version)

    logger.info(
        "OAuth request → version=%s  url=%s  client_id=%s  client_secret=%s",
        version, url, _mask(cid), _mask(secret),
    )

    last_resp = None
    for name, strategy in strategies:
        resp = strategy()
        if resp is None:
            continue  # network error, try next
        if resp.ok:
            data = resp.json()
            logger.info("OAuth succeeded with strategy: %s", name)
            return data["access_token"], int(data.get("expires_in", 3600))
        logger.warning(
            "OAuth strategy %s failed (%s): %s", name, resp.status_code, resp.text
        )
        last_resp = resp

    if last_resp is not None:
        logger.error("All OAuth strategies exhausted. Last: %s %s",
                     last_resp.status_code, last_resp.text)
        last_resp.raise_for_status()
    raise RuntimeError("All OAuth strategies failed due to network errors")
