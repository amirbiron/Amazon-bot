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


def client_secrets_exist() -> bool:
    return os.path.isfile(_secrets_path())
