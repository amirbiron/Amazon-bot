import requests
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from app import db, config

logger = logging.getLogger(__name__)

# All known Cognito token endpoints for the Creators API
_COGNITO_ENDPOINTS = {
    "us-east-1": "https://creatorsapi.auth.us-east-1.amazoncognito.com/oauth2/token",
    "eu-south-2": "https://creatorsapi.auth.eu-south-2.amazoncognito.com/oauth2/token",
    "us-west-2": "https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token",
}


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

# Some copy/paste sources (especially RTL languages) insert invisible Unicode
# marks or non-breaking spaces. Cognito then treats credentials as different
# strings and responds with {"error":"invalid_client"}.
_CRED_SANITIZE_RE = re.compile(
    r"[\s\u00A0\u200B\u200C\u200D\u200E\u200F\u202A-\u202E\u2066-\u2069\uFEFF]+"
)


def _sanitize_credential(value: str) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    return _CRED_SANITIZE_RE.sub("", value)


def _post_safe(url: str, **kwargs) -> requests.Response | None:
    """POST with network-error resilience so the fallback loop continues."""
    kwargs.setdefault("headers", _FORM_HEADERS)
    try:
        return requests.post(url, timeout=15, **kwargs)
    except requests.RequestException as exc:
        logger.warning("Network error reaching %s: %s", url, exc)
        return None


def _cognito_request(url: str, cid: str, secret: str) -> requests.Response | None:
    """Try body-credentials against a Cognito endpoint."""
    return _post_safe(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": cid,
            "client_secret": secret,
            "scope": "creatorsapi/default",
        },
    )


def _build_strategies(primary_url: str, cid: str, secret: str):
    """
    Build an ordered list of (name, callable) auth strategies.
    1. Primary Cognito endpoint (body creds, then Basic Auth).
    2. All other Cognito regional endpoints as fallback.
    """
    strategies = []

    # Primary endpoint — body credentials (most common)
    strategies.append(("Cognito+BodyCredentials", lambda: _cognito_request(
        primary_url, cid, secret,
    )))

    # Primary endpoint — Basic Auth
    strategies.append(("Cognito+BasicAuth", lambda: _post_safe(
        primary_url,
        data={"grant_type": "client_credentials", "scope": "creatorsapi/default"},
        auth=(cid, secret),
    )))

    # Fallback: try other regional Cognito endpoints (credentials might be
    # registered in a different region than the user selected)
    for region, url in _COGNITO_ENDPOINTS.items():
        if url == primary_url:
            continue  # already tried
        strategies.append((f"Cognito({region})+Body", lambda u=url: _cognito_request(
            u, cid, secret,
        )))

    return strategies


def _fetch_token():
    raw_cid = config.CREATORS_CREDENTIAL_ID
    raw_secret = config.CREATORS_CREDENTIAL_SECRET

    cid = _sanitize_credential(raw_cid)
    secret = _sanitize_credential(raw_secret)

    if cid != str(raw_cid) or secret != str(raw_secret):
        logger.warning(
            "Creators credentials contained whitespace/invisible characters; "
            "sanitized before OAuth request."
        )
    url = config.TOKEN_URL
    version = config.CREATORS_VERSION

    strategies = _build_strategies(url, cid, secret)

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
                "Hint: invalid_client means the Cognito user pool does not "
                "recognize these credentials. Common causes:\n"
                "  1. Credentials were created in Amazon Developer Console "
                "(LWA) instead of Associates Central → Creators API\n"
                "  2. Credentials were regenerated — use the latest ones\n"
                "  3. Creators API app not fully activated yet — contact "
                "Amazon Associates support\n"
                "  4. Trailing whitespace in credential values"
            )
        last_resp.raise_for_status()
    raise RuntimeError("All OAuth strategies failed due to network errors")
