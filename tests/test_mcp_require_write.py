"""Unit tests for the write-scope gate (`require_write` / `_token_scopes`).

Covers both auth modes: the OAuth path (verified access token exposes `.scopes`)
and the PAT-only fallback (scopes injected onto `request.state`).
"""

import pytest

pytest.importorskip("mcp")

import mcp.server.auth.middleware.auth_context as ac  # noqa: E402

from mcp_server.auth import require_write  # noqa: E402


class _Token:
    def __init__(self, scopes):
        self.scopes = scopes


class _Ctx:
    """Minimal stand-in for the tool Context (only request.state.scopes is read)."""

    def __init__(self, scopes):
        from types import SimpleNamespace

        self.request_context = SimpleNamespace(
            request=SimpleNamespace(state=SimpleNamespace(scopes=scopes))
        )


def test_require_write_oauth_allows_write(monkeypatch):
    monkeypatch.setattr(ac, "get_access_token", lambda: _Token(["read", "write"]))
    require_write(None)  # token present → ctx not needed; no raise


def test_require_write_oauth_denies_readonly(monkeypatch):
    monkeypatch.setattr(ac, "get_access_token", lambda: _Token(["read"]))
    with pytest.raises(PermissionError):
        require_write(None)


def test_require_write_pat_fallback_allows_write(monkeypatch):
    # No OAuth context → falls back to request.state.scopes (PAT-only mode).
    monkeypatch.setattr(ac, "get_access_token", lambda: None)
    require_write(_Ctx(["read", "write"]))  # no raise


def test_require_write_pat_fallback_denies_readonly(monkeypatch):
    monkeypatch.setattr(ac, "get_access_token", lambda: None)
    with pytest.raises(PermissionError):
        require_write(_Ctx(["read"]))


def test_require_write_denies_when_no_token_and_no_state(monkeypatch):
    monkeypatch.setattr(ac, "get_access_token", lambda: None)
    with pytest.raises(PermissionError):
        require_write(None)  # nothing anywhere → deny (fail closed)
