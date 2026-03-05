import base64
import os
import socket
import struct
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
# [Suggestion 2] Aggressive sanitization — strip ALL non-printable and
# non-ASCII characters, not just a known set.
_CRED_SANITIZE_RE = re.compile(
    r"[\s\u00A0\u200B\u200C\u200D\u200E\u200F\u202A-\u202E\u2066-\u2069\uFEFF]+"
)


def _sanitize_credential(value: str) -> str:
    """[Suggestion 2] Aggressively strip every non-printable / non-ASCII char."""
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    # First pass: known invisible characters
    value = _CRED_SANITIZE_RE.sub("", value)
    # Second pass: remove anything that is not printable ASCII (0x20-0x7E)
    cleaned = "".join(ch for ch in value if 0x20 <= ord(ch) <= 0x7E)
    return cleaned


def _validate_credential_chars(label: str, value: str) -> None:
    """[Suggestion 1] Scan character-by-character and report non-ASCII chars."""
    problems = []
    for i, ch in enumerate(value):
        code = ord(ch)
        if code > 127:
            cat = unicodedata.category(ch)
            name = unicodedata.name(ch, f"U+{code:04X}")
            problems.append(f"  pos {i}: {repr(ch)} (ord={code}, category={cat}, name={name})")
    if problems:
        logger.warning(
            "[Diagnostic] %s contains %d non-ASCII character(s):\n%s",
            label, len(problems), "\n".join(problems),
        )
    else:
        logger.debug("[Diagnostic] %s — all characters are valid ASCII", label)


def _post_safe(url: str, **kwargs) -> requests.Response | None:
    """POST with network-error resilience so the fallback loop continues."""
    kwargs.setdefault("headers", _FORM_HEADERS)

    # [Suggestion 3] Log the full request details (mask secrets in body)
    safe_data = dict(kwargs.get("data", {}))
    for secret_key in ("client_secret",):
        if secret_key in safe_data:
            safe_data[secret_key] = _mask(safe_data[secret_key])
    safe_headers = dict(kwargs.get("headers", _FORM_HEADERS))
    if "Authorization" in safe_headers:
        safe_headers["Authorization"] = safe_headers["Authorization"][:20] + "..."
    logger.debug(
        "[Diagnostic] OAuth request details → URL=%s  headers=%s  body=%s",
        url, safe_headers, safe_data,
    )

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


def _check_ntp_clock_drift() -> None:
    """[Suggestion 6] Compare local clock to an NTP server.
    More than 5 minutes drift can cause Cognito to reject requests."""
    NTP_SERVER = "pool.ntp.org"
    NTP_PORT = 123
    try:
        # Build a minimal NTP v3 client request (mode 3)
        data = b"\x1b" + 47 * b"\0"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(5)
            sock.sendto(data, (NTP_SERVER, NTP_PORT))
            resp, _ = sock.recvfrom(1024)

        # Extract transmit timestamp (bytes 40-47)
        if len(resp) >= 48:
            ntp_time = struct.unpack("!I", resp[40:44])[0]
            # NTP epoch is 1900-01-01, Unix epoch is 1970-01-01
            NTP_DELTA = 2208988800
            ntp_unix = ntp_time - NTP_DELTA
            local_unix = datetime.now(timezone.utc).timestamp()
            drift_seconds = abs(local_unix - ntp_unix)

            if drift_seconds > 300:  # 5 minutes
                logger.error(
                    "[Diagnostic] CLOCK DRIFT DETECTED: local clock is %.1fs "
                    "off from NTP (%s). Cognito may reject tokens!",
                    drift_seconds, NTP_SERVER,
                )
            else:
                logger.info(
                    "[Diagnostic] Clock drift: %.1fs from NTP — OK", drift_seconds,
                )
    except Exception as exc:
        logger.warning("[Diagnostic] Could not check NTP clock: %s", exc)


def _check_proxy_env() -> None:
    """[Suggestion 7] Scan environment for proxy/SSL settings that could
    interfere with the OAuth request."""
    proxy_vars = [
        "HTTP_PROXY", "http_proxy",
        "HTTPS_PROXY", "https_proxy",
        "NO_PROXY", "no_proxy",
        "SSL_CERT_FILE", "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    ]
    found = {}
    for var in proxy_vars:
        val = os.environ.get(var)
        if val:
            found[var] = val

    if found:
        logger.warning(
            "[Diagnostic] Proxy/SSL environment variables detected "
            "(may alter OAuth requests): %s", found,
        )
    else:
        logger.debug("[Diagnostic] No proxy/SSL environment variables set — OK")


def _verify_base64_encoding(cid: str, secret: str) -> None:
    """[Suggestion 4] Build client_id:client_secret, encode to base64,
    and log so the Authorization header can be verified manually."""
    raw = f"{cid}:{secret}".encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    logger.info(
        "[Diagnostic] Base64 of client_id:client_secret — length=%d, "
        "starts with %s...",
        len(b64), b64[:8],
    )


def _log_credential_lengths(raw_cid: str, raw_secret: str, cid: str, secret: str) -> None:
    """[Suggestion 5] Log credential lengths to detect hidden characters."""
    logger.info(
        "[Diagnostic] Credential lengths — "
        "raw client_id=%d, sanitized client_id=%d | "
        "raw client_secret=%d, sanitized client_secret=%d",
        len(str(raw_cid)), len(cid),
        len(str(raw_secret)), len(secret),
    )
    if len(str(raw_cid)) != len(cid):
        logger.warning(
            "[Diagnostic] client_id length changed after sanitization "
            "(%d → %d) — hidden characters were removed!",
            len(str(raw_cid)), len(cid),
        )
    if len(str(raw_secret)) != len(secret):
        logger.warning(
            "[Diagnostic] client_secret length changed after sanitization "
            "(%d → %d) — hidden characters were removed!",
            len(str(raw_secret)), len(secret),
        )


_last_diagnostics_at: float = 0.0
_DIAGNOSTICS_COOLDOWN = 300  # 5 minutes


def _run_diagnostics(raw_cid: str, raw_secret: str, cid: str, secret: str) -> None:
    """Run all diagnostic checks when OAuth fails with invalid_client.
    Skips if already run within the cooldown period to avoid log spam."""
    global _last_diagnostics_at
    import time
    now = time.monotonic()
    if now - _last_diagnostics_at < _DIAGNOSTICS_COOLDOWN:
        logger.info("[Diagnostic] Skipping — already ran %.0fs ago (cooldown=%ds)",
                    now - _last_diagnostics_at, _DIAGNOSTICS_COOLDOWN)
        return
    _last_diagnostics_at = now

    logger.info("=" * 60)
    logger.info("[Diagnostic] Running full OAuth diagnostics...")
    logger.info("=" * 60)

    # [Suggestion 1] Character validation
    _validate_credential_chars("raw client_id", str(raw_cid))
    _validate_credential_chars("raw client_secret", str(raw_secret))

    # [Suggestion 5] Length inspection
    _log_credential_lengths(raw_cid, raw_secret, cid, secret)

    # [Suggestion 4] Base64 verification
    _verify_base64_encoding(cid, secret)

    # [Suggestion 6] NTP clock check
    _check_ntp_clock_drift()

    # [Suggestion 7] Proxy/SSL check
    _check_proxy_env()

    # [Suggestion 8] Binary file reading check
    _check_binary_credential_reading()

    logger.info("=" * 60)
    logger.info("[Diagnostic] Diagnostics complete.")
    logger.info("=" * 60)


def _check_binary_credential_reading() -> None:
    """[Suggestion 8] Read raw decrypted bytes from the secrets file and check
    for encoding anomalies (e.g. BOM, non-UTF-8 bytes, non-ASCII in values)
    that json.loads may silently normalise."""
    try:
        from app.crypto import load_client_secrets_raw_bytes
        parsed, raw_bytes = load_client_secrets_raw_bytes()
        if not parsed:
            logger.debug("[Diagnostic] No client secrets file — skipping binary read check")
            return

        # Check for UTF-8 BOM
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            logger.warning("[Diagnostic] Secrets file contains a UTF-8 BOM prefix!")

        # Check each credential value at the byte level
        for key in ("CREATORS_API_CREDENTIAL_ID", "CREATORS_API_CREDENTIAL_SECRET"):
            val = parsed.get(key, "")
            env_val = os.environ.get(key, "")
            raw_encoded = val.encode("utf-8")
            non_ascii = [b for b in raw_encoded if b > 127]
            if non_ascii:
                logger.warning(
                    "[Diagnostic] %s from secrets file contains %d non-ASCII "
                    "byte(s) in raw payload",
                    key, len(non_ascii),
                )
            if val != env_val:
                logger.warning(
                    "[Diagnostic] %s MISMATCH: secrets file (len=%d) vs "
                    "env var (len=%d) — possible encoding divergence",
                    key, len(val), len(env_val),
                )
            else:
                logger.debug("[Diagnostic] %s — secrets file matches env var", key)
    except Exception as exc:
        logger.warning("[Diagnostic] Binary read check failed: %s", exc)


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
            # Run full diagnostics on invalid_client failure
            _run_diagnostics(raw_cid, raw_secret, cid, secret)
        last_resp.raise_for_status()
    raise RuntimeError("All OAuth strategies failed due to network errors")
