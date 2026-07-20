"""Unit tests for the admin gate (require_admin / is_admin_user) — fail-closed."""

import pytest

pytest.importorskip("mcp")

import mcp.server.auth.middleware.auth_context as ac  # noqa: E402

from mcp_server import auth as mcp_auth  # noqa: E402
from mcp_server.auth import is_admin_user, require_admin  # noqa: E402


class _Token:
    def __init__(self, subject, scopes=("read",)):
        self.subject = subject
        self.scopes = list(scopes)


def _set_admins(monkeypatch, ids):
    # The canonical source is config.ADMIN_USER_IDS — patch the resolver so the
    # tests don't depend on env parsing.
    monkeypatch.setattr(mcp_auth, "admin_user_ids", lambda: set(ids))


def test_admin_allowed(monkeypatch):
    _set_admins(monkeypatch, {42})
    monkeypatch.setattr(ac, "get_access_token", lambda: _Token("42"))
    assert require_admin(None) == 42


def test_non_admin_denied(monkeypatch):
    _set_admins(monkeypatch, {42})
    monkeypatch.setattr(ac, "get_access_token", lambda: _Token("7"))
    with pytest.raises(PermissionError):
        require_admin(None)


def test_empty_admin_list_denies_everyone(monkeypatch):
    # fail-closed: no admins configured => nobody is admin.
    _set_admins(monkeypatch, set())
    monkeypatch.setattr(ac, "get_access_token", lambda: _Token("42"))
    with pytest.raises(PermissionError):
        require_admin(None)


def test_unauthenticated_denied(monkeypatch):
    _set_admins(monkeypatch, {42})
    monkeypatch.setattr(ac, "get_access_token", lambda: None)
    with pytest.raises(PermissionError):
        require_admin(None)  # no token, no request state


def test_chatops_escape_hatch_is_ignored(monkeypatch):
    # chatops' CHATOPS_ALLOW_ALL_IF_NO_ADMINS must have NO effect here: with an
    # empty admin set, everyone stays denied even when the hatch env is set.
    monkeypatch.setenv("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")
    _set_admins(monkeypatch, set())
    assert is_admin_user(42) is False


def test_is_admin_user_bad_input():
    assert is_admin_user("not-a-number") is False
    assert is_admin_user(None) is False


def test_admin_user_ids_fail_closed(monkeypatch):
    # If the config layer is unavailable, the set must be empty (deny), not crash.
    import builtins

    real_import = builtins.__import__

    def _no_config(name, *a, **k):
        if name == "config":
            raise RuntimeError("config unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_config)
    assert mcp_auth.admin_user_ids() == set()
