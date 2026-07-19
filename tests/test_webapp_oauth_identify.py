"""Tests for the webapp /oauth/identify identity bridge (Flask test client)."""

import hashlib
import hmac
import re
import time

import pytest

pytest.importorskip("flask")

from flask import Flask  # noqa: E402

from mcp_server.oauth_identity import verify_identity  # noqa: E402
from webapp.routes.auth_routes import auth_bp  # noqa: E402

SECRET = "unit-test-secret-key-0123456789"  # ≥ MIN_SECRET_LENGTH
MCP = "https://mcp.example.com"
BOT_TOKEN = "123456:ABC-test-token"


def _client(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", MCP)
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("BOT_TOKEN", BOT_TOKEN)
    app = Flask(__name__)
    app.secret_key = SECRET
    app.register_blueprint(auth_bp)
    return app.test_client()


def _tg_hash(fields: dict) -> str:
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    return hmac.new(secret_key, dcs.encode(), hashlib.sha256).hexdigest()


def _form_fields(html_text: str) -> dict:
    """Extract hidden input name→value pairs from the handoff POST form."""
    return dict(re.findall(r'name="([^"]+)"\s+value="([^"]*)"', html_text))


def test_missing_params_400(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/oauth/identify").status_code == 400


def test_open_redirect_guard(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/oauth/identify?txn=t1&return=https://evil.com/x")
    assert r.status_code == 400


def test_open_redirect_guard_rejects_lookalike_host(monkeypatch):
    # A host that merely *starts with* the configured base must be rejected.
    c = _client(monkeypatch)
    r = c.get("/oauth/identify?txn=t1&return=https://mcp.example.com.evil.com/oauth/consent")
    assert r.status_code == 400


def test_open_redirect_guard_rejects_scheme_downgrade(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/oauth/identify?txn=t1&return=http://mcp.example.com/oauth/consent")
    assert r.status_code == 400


def test_session_identity_posts_signed_handoff(monkeypatch):
    # The assertion must be handed off via a POST form body — never in the URL.
    c = _client(monkeypatch)
    with c.session_transaction() as sess:
        sess["user_id"] = 42
    r = c.get(f"/oauth/identify?txn=t1&return={MCP}/oauth/consent", follow_redirects=False)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'method="post"' in body and f'action="{MCP}/oauth/consent"' in body
    f = _form_fields(body)
    assert f["txn"] == "t1" and f["user_id"] == "42"
    assert verify_identity(SECRET, f["user_id"], f["txn"], f["exp"], f["sig"])


def test_misconfigured_secret_fails_closed(monkeypatch):
    # With a missing/default SECRET_KEY we must never sign with a guessable key.
    c = _client(monkeypatch)
    monkeypatch.setenv("SECRET_KEY", "dev-secret-key-change-in-production")
    with c.session_transaction() as sess:
        sess["user_id"] = 42
    r = c.get(f"/oauth/identify?txn=t1&return={MCP}/oauth/consent", follow_redirects=False)
    assert r.status_code == 500


def test_short_secret_fails_closed(monkeypatch):
    # A too-short key is refused, same as a missing/default one.
    c = _client(monkeypatch)
    monkeypatch.setenv("SECRET_KEY", "short")
    with c.session_transaction() as sess:
        sess["user_id"] = 42
    r = c.get(f"/oauth/identify?txn=t1&return={MCP}/oauth/consent", follow_redirects=False)
    assert r.status_code == 500


def test_no_session_shows_widget(monkeypatch):
    c = _client(monkeypatch)
    r = c.get(f"/oauth/identify?txn=t1&return={MCP}/oauth/consent")
    assert r.status_code == 200
    assert "telegram-widget.js" in r.get_data(as_text=True)


def test_telegram_branch_posts_handoff_and_ignores_extra_params(monkeypatch):
    c = _client(monkeypatch)
    tg = {"id": "77", "first_name": "A", "auth_date": str(int(time.time()))}
    h = _tg_hash(tg)
    # txn/return are extra params that Telegram never signs — must be ignored.
    url = (
        f"/oauth/identify?txn=t9&return={MCP}/oauth/consent"
        f"&id=77&first_name=A&auth_date={tg['auth_date']}&hash={h}"
    )
    r = c.get(url, follow_redirects=False)
    assert r.status_code == 200
    f = _form_fields(r.get_data(as_text=True))
    assert f["user_id"] == "77" and f["txn"] == "t9"
    assert verify_identity(SECRET, "77", "t9", f["exp"], f["sig"])


def test_telegram_branch_rejects_bad_hash(monkeypatch):
    c = _client(monkeypatch)
    url = (
        f"/oauth/identify?txn=t9&return={MCP}/oauth/consent"
        f"&id=77&first_name=A&auth_date={int(time.time())}&hash=deadbeef"
    )
    assert c.get(url).status_code == 401
