"""Unit tests for the signed identity assertion (webapp <-> MCP)."""

import pytest

from mcp_server.oauth_identity import sign_identity, verify_identity

SECRET = "shared-secret-key"


def test_sign_verify_roundtrip():
    exp, sig = sign_identity(SECRET, 42, "txn1")
    assert verify_identity(SECRET, 42, "txn1", exp, sig)
    # string inputs (as they arrive from query/form params) also verify
    assert verify_identity(SECRET, "42", "txn1", str(exp), sig)


def test_verify_rejects_tampering():
    exp, sig = sign_identity(SECRET, 42, "txn1")
    assert not verify_identity(SECRET, 43, "txn1", exp, sig)  # user mismatch
    assert not verify_identity(SECRET, 42, "txn2", exp, sig)  # txn mismatch
    assert not verify_identity("other-secret", 42, "txn1", exp, sig)  # wrong key
    assert not verify_identity(SECRET, 42, "txn1", exp, "deadbeef")  # bad sig
    assert not verify_identity(SECRET, 42, "txn1", exp, "")  # empty sig


def test_verify_rejects_expired():
    exp, sig = sign_identity(SECRET, 42, "txn1", ttl=100)
    assert verify_identity(SECRET, 42, "txn1", exp, sig, now=exp - 1)
    assert not verify_identity(SECRET, 42, "txn1", exp, sig, now=exp + 1)


def test_verify_rejects_non_numeric():
    exp, sig = sign_identity(SECRET, 42, "txn1")
    assert not verify_identity(SECRET, "abc", "txn1", exp, sig)
    assert not verify_identity(SECRET, 42, "txn1", "notint", sig)


def test_empty_secret_is_refused():
    # An empty signing key would let anyone forge an assertion, so signing must
    # raise and verification must always fail — never silently use a blank key.
    with pytest.raises(ValueError):
        sign_identity("", 42, "txn1")
    # Even a signature that "matches" an empty-key HMAC must not verify.
    import hashlib
    import hmac

    forged = hmac.new(b"", b"42:txn1:9999999999", hashlib.sha256).hexdigest()
    assert not verify_identity("", 42, "txn1", 9999999999, forged)


def test_assert_strong_secret():
    from mcp_server.oauth_identity import INSECURE_DEFAULT_SECRET, assert_strong_secret

    assert_strong_secret("a-real-strong-random-secret")  # ok: no raise
    # Rejected: empty, the well-known default, and too-short (weak) keys.
    for bad in ("", INSECURE_DEFAULT_SECRET, "short", "x" * 15):
        with pytest.raises(RuntimeError):
            assert_strong_secret(bad)
