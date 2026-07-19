"""Signed identity assertion shared by the webapp and the MCP consent route.

After the webapp authenticates the user via Telegram, it hands the MCP service a
short-lived, HMAC-signed assertion of ``user_id`` bound to the specific OAuth
transaction (``txn``). Both services import this module so the sign/verify logic
is identical and lives in one place.

The signing key is the shared ``SECRET_KEY`` (already common to bot + webapp).
Stdlib-only, so it is trivially unit-testable and importable from either process.
"""

from __future__ import annotations

import hashlib
import hmac
import time

DEFAULT_TTL_SECONDS = 300  # 5 min — the user should finish consent promptly


def _message(user_id: int, txn: str, exp: int) -> bytes:
    return f"{int(user_id)}:{txn}:{int(exp)}".encode()


def sign_identity(
    secret: str, user_id: int, txn: str, *, ttl: int = DEFAULT_TTL_SECONDS
) -> tuple[int, str]:
    """Return ``(exp, signature)`` for a user_id bound to a txn.

    Refuses an empty secret: signing with a blank HMAC key would let anyone who
    knows the (empty) key forge an identity assertion.
    """
    if not secret:
        raise ValueError("SECRET_KEY is not set; cannot sign identity assertion")
    exp = int(time.time()) + int(ttl)
    sig = hmac.new(secret.encode(), _message(user_id, txn, exp), hashlib.sha256).hexdigest()
    return exp, sig


def verify_identity(
    secret: str, user_id: str | int, txn: str, exp: str | int, sig: str, *, now: int | None = None
) -> bool:
    """Constant-time verify of a signed identity assertion (incl. expiry).

    An empty secret can never produce a valid assertion (see ``sign_identity``),
    so reject outright instead of verifying against a blank key.
    """
    if not secret:
        return False
    try:
        exp_i = int(exp)
        uid_i = int(user_id)
    except (TypeError, ValueError):
        return False
    if (now if now is not None else int(time.time())) > exp_i:
        return False
    expected = hmac.new(secret.encode(), _message(uid_i, txn, exp_i), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(sig or ""))
