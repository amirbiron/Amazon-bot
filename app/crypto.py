"""
Encrypt / decrypt client secrets using an auto-generated key.
The key lives on the persistent disk — not in env vars, not in git.
No master password needed.
"""
import json
import os

from cryptography.fernet import Fernet, InvalidToken


def _data_dir() -> str:
    """Resolve the persistent data directory (Render Disk or project root)."""
    db_path = os.getenv("DB_PATH")
    if db_path:
        return os.path.dirname(db_path) or "."
    return os.path.dirname(os.path.dirname(__file__))


def _key_path() -> str:
    return os.path.join(_data_dir(), ".encryption.key")


def _secrets_path() -> str:
    return os.path.join(_data_dir(), "client_secrets.enc")


def _get_or_create_key() -> bytes:
    """Load the Fernet key from disk, or generate one on first use."""
    path = _key_path()
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def save_client_secrets(secrets: dict) -> None:
    """Encrypt and write client secrets to disk."""
    key = _get_or_create_key()
    fernet = Fernet(key)
    payload = json.dumps(secrets).encode()
    token = fernet.encrypt(payload)
    path = _secrets_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(token)


def load_client_secrets() -> dict:
    """Read and decrypt client secrets.  Returns {} if file doesn't exist."""
    path = _secrets_path()
    if not os.path.isfile(path):
        return {}
    key = _get_or_create_key()
    fernet = Fernet(key)
    with open(path, "rb") as f:
        token = f.read()
    try:
        payload = fernet.decrypt(token)
    except InvalidToken:
        return {}
    return json.loads(payload)


def load_client_secrets_raw_bytes() -> tuple[dict, bytes]:
    """[Suggestion 8] Decrypt client secrets and return both the parsed dict
    AND the raw decrypted bytes, so callers can inspect byte-level content
    (e.g. detect encoding issues that json.loads silently normalises).
    Returns ({}, b"") if file doesn't exist or decryption fails."""
    path = _secrets_path()
    if not os.path.isfile(path):
        return {}, b""
    key = _get_or_create_key()
    fernet = Fernet(key)
    with open(path, "rb") as f:
        token = f.read()
    try:
        raw_payload = fernet.decrypt(token)
    except InvalidToken:
        return {}, b""
    return json.loads(raw_payload.decode("utf-8")), raw_payload


def client_secrets_exist() -> bool:
    return os.path.isfile(_secrets_path())


# ── Access token on disk (overrides PANEL_ACCESS_TOKEN env var) ───────────────

def _token_path() -> str:
    return os.path.join(_data_dir(), ".panel_token")


def save_access_token(token: str) -> None:
    """Save a new access token to the persistent disk."""
    path = _token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)


def load_access_token() -> str | None:
    """Load the client-set access token from disk, or None if not set."""
    path = _token_path()
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        return f.read().strip() or None


def client_owns_token() -> bool:
    """True if the client has already changed the access token."""
    return os.path.isfile(_token_path())
