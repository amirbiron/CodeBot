import os
import base64
from typing import Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # cryptography may not be installed in dev
    Fernet = None
    InvalidToken = Exception


ENC_PREFIX = "enc:"


def _get_fernet() -> Optional["Fernet"]:
    key_b64 = os.getenv("TOKEN_ENC_KEY")
    if not key_b64 or not Fernet:
        return None
    try:
        # Accept raw 32-byte key (base64) or already generated Fernet key
        try:
            key = base64.urlsafe_b64decode(key_b64)
            if len(key) != 32:
                # Not 32 bytes after decode; maybe already a Fernet key
                raise ValueError
            key_fernet = base64.urlsafe_b64encode(key)
        except Exception:
            # Assume it's already a Fernet key
            key_fernet = key_b64.encode()
        return Fernet(key_fernet)
    except Exception:
        return None


def encrypt_secret(plaintext: str) -> Optional[str]:
    f = _get_fernet()
    if not f:
        return None
    token = f.encrypt(plaintext.encode("utf-8"))
    return ENC_PREFIX + token.decode("utf-8")


def decrypt_secret(stored: str) -> Optional[str]:
    if not stored:
        return None
    if not stored.startswith(ENC_PREFIX):
        return stored
    f = _get_fernet()
    if not f:
        return None
    token = stored[len(ENC_PREFIX):].encode("utf-8")
    try:
        return f.decrypt(token).decode("utf-8")
    except InvalidToken:
        return None