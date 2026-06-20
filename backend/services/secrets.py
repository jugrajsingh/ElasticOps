import json
import os
import secrets as _secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from config.settings import get_settings


def _secrets_path() -> Path:
    return Path(get_settings().security.secrets_file)


@lru_cache
def _persisted() -> dict[str, str]:
    """Load secrets from the gitignored secrets file, generating + writing them on first use."""
    path = _secrets_path()
    if path.exists():
        return json.loads(path.read_text())
    data = {
        "jwt_secret": _secrets.token_urlsafe(48),
        "fernet_key": Fernet.generate_key().decode(),
    }
    # Create with 0o600 from the start; O_EXCL makes it atomic + race-safe (no
    # window where the freshly generated secret sits world-readable on disk).
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return json.loads(path.read_text())
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return data


def get_jwt_secret() -> str:
    configured = get_settings().auth.jwt_secret
    return configured if configured else _persisted()["jwt_secret"]


@lru_cache
def _fernet() -> Fernet:
    configured = get_settings().security.encryption_key
    key = configured if configured else _persisted()["fernet_key"]
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    return _fernet().decrypt(token.encode()).decode()
