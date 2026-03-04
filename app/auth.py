import requests
import logging
from datetime import datetime, timedelta, timezone
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
        expires_at = datetime.fromisoformat(cached["expires_at"]).replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < expires_at - timedelta(minutes=5):
            return cached["access_token"]

    logger.info("Fetching new OAuth token...")
    token, expires_in = _fetch_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    db.set_token_cache(token, expires_at.isoformat())
    logger.info("New token cached, expires at %s", expires_at.isoformat())
    return token


def _mask(value: str) -> str:
    return (value[:4] + "...") if value else "<empty>"


_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


def _post_safe(url: str, **kwargs) -> requests.Response | None:
    """POST with network-error resilience so the fallback loop continues."""
    kwargs.setdefault("headers", _FORM_HEADERS)
    try:
        return requests.post(url, timeout=15, **kwargs)
    except requests.RequestException as exc:
        logger.warning("Network error reaching %s: %s", url, exc)
        return None


def _build_strategies(url: str, cid: str, secret: str, version: str):
    """
    Build an ordered list of (name, callable) auth strategies.
    v2.x → Cognito endpoint (body creds, then Basic Auth).
    v3.x → Same Cognito endpoint (all versions use Cognito).
    """
    strategies = []

    # All versions: try Cognito with creatorsapi/default scope first
    strategies.append(("Cognito+BodyCredentials", lambda: _post_safe(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": cid,
            "client_secret": secret,
            "scope": "creatorsapi/default",
        },
    )))
    strategies.append(("Cognito+BasicAuth", lambda: _post_safe(
        url,
        data={"grant_type": "client_credentials", "scope": "creatorsapi/default"},
        auth=(cid, secret),
    )))

    return strategies


def _fetch_token():
    cid = config.CREATORS_CREDENTIAL_ID.strip()
    secret = config.CREATORS_CREDENTIAL_SECRET.strip()
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
        if "invalid_client" in last_resp.text:
            logger.error(
                "Hint: invalid_client usually means credentials are wrong, "
                "have trailing whitespace, or the Creators API app is not "
                "fully activated yet. Try regenerating credentials in "
                "Associates Central → Tools → Creators API."
            )
        last_resp.raise_for_status()
    raise RuntimeError("All OAuth strategies failed due to network errors")
