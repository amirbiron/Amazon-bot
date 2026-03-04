"""
Encrypt / decrypt secrets using a master password.
Uses PBKDF2 key derivation + Fernet (AES-128-CBC with HMAC).
"""
import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

SECRETS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets.enc")
SALT_SIZE = 16
PBKDF2_ITERATIONS = 480_000


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt_secrets(secrets: dict, master_password: str, path: str = SECRETS_FILE) -> None:
    """Encrypt a dict of key-value secrets and write to disk."""
    salt = os.urandom(SALT_SIZE)
    key = _derive_key(master_password, salt)
    f = Fernet(key)
    payload = json.dumps(secrets).encode()
    token = f.encrypt(payload)
    with open(path, "wb") as fh:
        fh.write(salt + token)


def decrypt_secrets(master_password: str, path: str = SECRETS_FILE) -> dict:
    """Read encrypted file and return the secrets dict.  Raises on wrong password."""
    with open(path, "rb") as fh:
        raw = fh.read()
    salt, token = raw[:SALT_SIZE], raw[SALT_SIZE:]
    key = _derive_key(master_password, salt)
    f = Fernet(key)
    try:
        payload = f.decrypt(token)
    except InvalidToken:
        raise ValueError("סיסמה שגויה או קובץ פגום")
    return json.loads(payload)


def secrets_file_exists(path: str = SECRETS_FILE) -> bool:
    return os.path.isfile(path)
