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

# The placeholder value app code falls back to when SECRET_KEY is unset. It is
# public knowledge, so signing identity assertions with it would let anyone forge
# a user_id. OAuth mode must refuse to start with it (see assert_strong_secret).
INSECURE_DEFAULT_SECRET = "dev-secret-key-change-in-production"
# Floor for a usable signing key. A real random key is far longer (e.g.
# ``secrets.token_urlsafe(48)`` → 64 chars); this only rejects obviously weak
# values so a short/guessable string can't sign identity assertions.
MIN_SECRET_LENGTH = 16


def assert_strong_secret(secret: str) -> None:
    """Raise ``RuntimeError`` unless ``secret`` is a real, non-default signing key.

    Called at OAuth startup so a deployment can never sign the user-identity
    assertion with an empty, well-known, or too-short key. The same value must be
    configured on both the webapp and the MCP service (they sign/verify the same
    message).
    """
    if not secret or secret == INSECURE_DEFAULT_SECRET or len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            "SECRET_KEY must be set to a strong, random value "
            f"(≥{MIN_SECRET_LENGTH} chars, identical on the webapp and MCP services) "
            "for OAuth mode — it signs the user-identity assertion bridged between them."
        )


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
