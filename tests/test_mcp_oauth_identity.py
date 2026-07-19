"""Unit tests for the signed identity assertion (webapp <-> MCP)."""

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
