"""Unit tests for the repo secrets-path policy (mandatory, fail-closed)."""

import pytest

from mcp_server import repo_policy
from mcp_server.repo_policy import is_denied


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "config/.env",  # nested
        "a/b/.env.production",
        ".ENV",  # case variant
        "certs/server.pem",
        "keys/private.key",
        "id_rsa",
        ".ssh/id_rsa.pub",
        "deploy/id_ed25519",
        "secrets.yaml",
        "conf/secrets.json",
        "credentials.json",
        "gcp/credentials_prod.yaml",
        "store.p12",
        "win/cert.pfx",
        ".netrc",
        ".npmrc",
        "android/release.keystore",
    ],
)
def test_denied_paths(path):
    assert is_denied(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "main.py",
        "src/app/utils.py",
        "envelope.py",  # starts with 'env' but no leading dot
        "environment.md",
        "key_utils.py",  # 'key' not as extension
        "docs/keys.md",
        "secrets_test.py",  # 'secrets_' != 'secrets.'
        "tests/test_secrets_handling.py",
        "README.md",
        "config/settings.yaml",
    ],
)
def test_allowed_paths(path):
    assert is_denied(path) is False


def test_empty_and_traversal_denied():
    assert is_denied("") is True
    assert is_denied(None) is True
    assert is_denied("..") is True


def test_windows_separators_normalized():
    assert is_denied("config\\.env") is True


def test_extra_patterns_from_env(monkeypatch):
    monkeypatch.setenv("MCP_REPO_DENYLIST_EXTRA", "*.sqlite, private/*")
    assert is_denied("data/app.sqlite") is True
    assert is_denied("private/notes.md") is True
    monkeypatch.delenv("MCP_REPO_DENYLIST_EXTRA")
    assert is_denied("data/app.sqlite") is False


def test_fail_closed_on_internal_error(monkeypatch):
    # If pattern evaluation blows up, the path must be treated as denied.
    def _boom(*a, **k):
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(repo_policy.fnmatch, "fnmatchcase", _boom)
    assert is_denied("main.py") is True
